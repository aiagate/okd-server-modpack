"""Read-only public verification: approval, exact bytes, parent, Server Pack type."""
import argparse,hashlib,http.client,json,re,subprocess,time
from pathlib import Path
import publish_pair as pair
import release

HOST='www.curseforge.com'


def get(host,path,limit):
    connection=http.client.HTTPSConnection(host,timeout=30)
    try:
        connection.request('GET',path,headers={'User-Agent':'OKD-publication-verifier'})
        response=connection.getresponse()
        release.need(response.status==200,'public verification HTTP failure')
        data=response.read(limit+1)
        release.need(len(data)<=limit,'public verification response exceeds limit')
        return data
    finally:
        connection.close()


def public_json(path):
    value=release.parse_json(get(HOST,path,2*1024*1024))
    release.need(isinstance(value,dict) and 'data' in value,'public API shape changed')
    return value['data']


def assess(identity,client_id,server_id,assets,client,server,children):
    report=dict(schema_version=1,**identity,client_file_id=client_id,server_file_id=server_id,
        client_approved=False,server_approved=False,parent_link_verified=False,
        server_pack_classification_verified=False,byte_identity_verified=False,
        publication_complete=False,status='waiting_for_moderation')
    for kind,row,fid in (('client',client,client_id),('server',server,server_id)):
        if row is None:continue
        release.need(isinstance(row,dict) and row.get('id')==fid and
            row.get('projectId')==identity['project_id'] and
            row.get('fileName')==assets[kind]['name'] and row.get('fileLength')==assets[kind]['size'],
            'public file identity differs from recorded Release')
        report[kind+'_approved']=row.get('status')==4
    if not (report['client_approved'] and report['server_approved']):return report
    release.need(isinstance(children,list),'public additional-files shape changed')
    matches=[row for row in children if isinstance(row,dict) and row.get('id')==server_id]
    report['parent_link_verified']=len(matches)==1 and matches[0].get('parentProjectFileId')==client_id and matches[0].get('projectId')==identity['project_id']
    if not report['parent_link_verified']:
        report['status']='parent_link_not_confirmed';return report
    # The public web API exposes parent counters, not a type on each child row.
    # If all listed children are Server Packs, this exact child is classified.
    # Mixed types remain ambiguous; never infer type from filename/display name.
    count=client.get('additionalFilesCount');server_count=client.get('additionalServerPackFilesCount')
    classified=(client.get('hasServerPack') is True and type(count) is int and type(server_count) is int and
        count==server_count==len(children) and count>0)
    report['server_pack_classification_verified']=classified
    if not classified:
        report['status']='server_pack_setting_required_or_ambiguous'
        report['required_action']={
            'action':'inspect_existing_server_file_and_set_server_pack_in_author_dashboard',
            'project_id':identity['project_id'],'client_file_id':client_id,'server_file_id':server_id,
            'retry_submission':False}
        return report
    report['status']='approved_waiting_for_byte_verification'
    return report


def verify(version,project):
    release.need(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?',version), 'invalid version')
    raw=subprocess.check_output(['gh','release','view','v'+version,'--repo',pair.REPOSITORY,'--json','assets'],stderr=subprocess.PIPE)
    rows=release.parse_json(raw)['assets'];assets={}
    for kind,suffix in (('client',''),('server','-serverpack')):
        expected=f'okd-server-modpack-{version}{suffix}.zip'
        found=[a for a in rows if a['name']==expected]
        release.need(len(found)==1,'recorded release ZIP is missing/ambiguous')
        asset=found[0]
        release.need(re.fullmatch(r'sha256:[0-9a-f]{64}',asset.get('digest','')) and
            release.positive(asset['size']) and asset['size']<=release.MAX_ZIP,'invalid recorded ZIP metadata')
        assets[kind]=asset
    identity=pair.fingerprint(project,version,assets['client']['digest'][7:],assets['server']['digest'][7:])
    journal=pair.GitHubJournal('v'+version,identity)
    c=journal.read('client','result');s=journal.read('server','result')
    release.need(c is not None and s is not None,'both acceptance records are required')
    client_id=pair.check_record(c,identity,'client');server_id=pair.check_record(s,identity,'server',client_id)
    base=f'/api/v1/mods/{project}/files/'
    client=public_json(base+str(client_id));server=public_json(base+str(server_id))
    children=public_json(base+str(client_id)+'/additional-files') if client and server else None
    report=assess(identity,client_id,server_id,assets,client,server,children)
    if report['status']=='approved_waiting_for_byte_verification':
        for kind,row,fid in (('client',client,client_id),('server',server,server_id)):
            name=row['fileName'] # exact known release filename, no private URL/input
            raw=get('mediafilez.forgecdn.net',f'/files/{fid//1000}/{fid%1000}/{name}',release.MAX_ZIP)
            release.need(hashlib.sha256(raw).hexdigest()==identity[kind+'_sha256'],'public CDN ZIP bytes differ')
        report.update(status='approved_public_server_pack_verified',byte_identity_verified=True,publication_complete=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=0)
    args=parser.parse_args()
    report={'schema_version':1,'publication_complete':False,'status':'verification_unconfirmed'}
    if args.receipt.exists():
        print('STOP: use a new verification receipt; existing file preserved.')
        return 1
    try:
        meta=release.parse_json(Path('pack/release.json').read_bytes())
        release.need(0<=args.wait_seconds<=900,'invalid read-only wait limit')
        deadline=time.monotonic()+args.wait_seconds
        while True:
            report=verify(args.version or meta['version'],meta['project_id'])
            if report['status']!='waiting_for_moderation' or time.monotonic()>=deadline:break
            time.sleep(min(30,max(0,deadline-time.monotonic())))
    except (release.Invalid,OSError,ValueError,KeyError,subprocess.CalledProcessError,http.client.HTTPException):
        # Do not retain HTTP bodies, URL redirects, exceptions or account data.
        pass
    args.receipt.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if report.get('publication_complete'):return 0
    if report['status']=='waiting_for_moderation':return 0 # receipt explicitly says incomplete
    return 1

if __name__=='__main__':raise SystemExit(main())
