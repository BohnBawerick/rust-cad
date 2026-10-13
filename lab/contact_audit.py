#!/usr/bin/env python3
"""Diagnostic after search: normalize collinear edge subdivisions before incidence checks."""
import collections,json,math,subprocess,tempfile
from pathlib import Path
from oracle import mesh_metrics
ROOT=Path(__file__).resolve().parent

def check(out):
    points=[];index={};ids=[]
    for p in out['points']:
        key=tuple(round(v,8) for v in p)
        if key not in index:index[key]=len(points);points.append(key)
        ids.append(index[key])
    edges=collections.Counter();oriented_edges=collections.Counter();groups=collections.defaultdict(set)
    def line_key(a,b):
        pa,pb=points[a],points[b];v=[pb[k]-pa[k] for k in range(3)];length=math.sqrt(sum(x*x for x in v))
        if not length:return None
        direction=[x/length for x in v];axis=max(range(3),key=lambda k:abs(direction[k]))
        if direction[axis]<0:direction=[-x for x in direction]
        projection=sum(pa[k]*direction[k] for k in range(3))
        origin=[pa[k]-projection*direction[k] for k in range(3)]
        return tuple(round(x,6) for x in direction+origin)
    for triangle in out['triangles']:
        for a,b in zip(triangle,triangle[1:]+triangle[:1]):
            a,b=ids[a],ids[b];edge=tuple(sorted([a,b]));edges[edge]+=1;oriented_edges[edge]+=1 if a<b else -1
            groups[line_key(a,b)].update([a,b])
    segments=collections.Counter();orientation=collections.Counter();split_edges=0
    for (a,b),count in edges.items():
        pa,pb=points[a],points[b];v=[pb[k]-pa[k] for k in range(3)];length2=sum(x*x for x in v)
        if not length2:continue
        cuts=[(0,a),(1,b)]
        for i in groups[line_key(a,b)]:
            if i in [a,b]:continue
            p=points[i];t=sum((p[k]-pa[k])*v[k] for k in range(3))/length2
            if 1e-9<t<1-1e-9 and math.dist(p,[pa[k]+t*v[k] for k in range(3)])<2e-8:cuts.append((t,i))
        cuts.sort();split_edges+=len(cuts)>2
        for (_,u),(_,w) in zip(cuts,cuts[1:]):
            edge=tuple(sorted([u,w]));segments[edge]+=count;orientation[edge]+=oriented_edges[(a,b)]*(1 if u<w else -1)
    bad=[dict(endpoints=[points[a],points[b]],uses=n,winding=orientation[(a,b)]) for (a,b),n in segments.items() if n!=2 or orientation[(a,b)]!=0]
    return dict(original_mesh_closed=mesh_metrics(out)['mesh_closed'],subdivided_edges=split_edges,normalized_mesh_closed=not bad,bad_segments=bad)

def raw(case_id):
    with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
        folder=Path(folder);c=json.loads((ROOT/'corpus/public'/(case_id+'.json')).read_text())
        (folder/'case.json').write_text(json.dumps(c))
        cmd=['prlimit','--as=4294967296','--cpu=8','--','bwrap','--unshare-all','--die-with-parent','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(ROOT/'target/final-probe'),'/probe','--ro-bind',str(folder/'case.json'),'/case.json','--','/probe','/case.json']
        return json.loads(subprocess.check_output(cmd,timeout=8,env={'PATH':'/usr/bin:/bin','LC_ALL':'C','RAYON_NUM_THREADS':'1'}))
def main():
    out=ROOT/'contact-audit';out.mkdir(exist_ok=True)
    results=[]
    for case_id in ['public-007','public-046','public-085','public-124','public-166','public-178','public-229','public-315']:
        geometry=raw(case_id);(out/(case_id+'-raw.json')).write_text(json.dumps(geometry)+'\n')
        results.append(dict(id=case_id,**check(geometry)))
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps([dict(id=r['id'],original=r['original_mesh_closed'],normalized=r['normalized_mesh_closed'],bad_segments=len(r['bad_segments'])) for r in results],indent=2))
if __name__=='__main__':main()
