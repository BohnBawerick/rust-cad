"""Synthetic recipes. Generate once, then freeze the files before experiments."""
import json, random
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def box(p=(0,0,0),d=(1,1,1)):
    return dict(kind='box',origin=list(p),size=list(d))
def cyl(p=(0,0,0),r=1,h=1):
    return dict(kind='cylinder',origin=list(p),radius=r,height=h)
def generate(split,seed,n,out=None):
    rng=random.Random(seed); cases=[]
    def add(group,op,a,**kw):
        i=len(cases);cases.append(dict(id=f'{split}-{i:03d}',group=group,op=op,a=a,boolean_tol=.05,mesh_tol=.002,**kw))
    relations=['disjoint','touch_face','touch_edge','touch_vertex','overlap','contains','contained','identical','near_gap','near_overlap','far_negative','offset_overlap','thin']
    for i in range(n):
        s=rng.choice([.5,1.,2.,5.]);p=[rng.uniform(-5,5) for _ in range(3)];d=[s*rng.uniform(1,2) for _ in range(3)]
        a=box(p,d);q=p.copy();e=d.copy();rel=relations[i%len(relations)]
        if rel in ['disjoint','touch_face','near_gap','near_overlap']:q[0]+=d[0]+{'disjoint':s,'touch_face':0,'near_gap':s*1e-4,'near_overlap':-s*1e-4}[rel]
        elif rel=='touch_edge':q[0]+=d[0];q[1]+=d[1]
        elif rel=='touch_vertex':q=[p[j]+d[j] for j in range(3)]
        elif rel in ['overlap','offset_overlap']:q=[p[j]+d[j]*([.4,0,0] if rel=='overlap' else [.3,.4,.2])[j] for j in range(3)]
        elif rel=='contains':q=[p[j]+.2*d[j] for j in range(3)];e=[.6*x for x in d]
        elif rel=='contained':q=[p[j]-.2*d[j] for j in range(3)];e=[1.4*x for x in d]
        elif rel=='far_negative':q[1]-=3*d[1]
        elif rel=='thin':q[0]+=d[0]-.001*s;e[0]=.002*s
        for op in ['difference','union','intersection']:add('boxes',op,a,b=box(q,e),relation=rel,rotation=rng.choice([0,0,.31,.77,1.5707963267948966]))
    for i in range(max(4,n//2)):
        r=rng.uniform(.2,1);h=rng.uniform(.5,2);d=r*rng.choice([0,1,2,2.001,3]);p=[rng.uniform(-2,2) for _ in range(3)]
        for op in ['difference','union','intersection']:add('cylinders',op,cyl(p,r,h),b=cyl([p[0]+d,p[1],p[2]],r,h),relation=f'd/r={d/r}')
    for i in range(max(3,n//4)):
        p=[rng.uniform(-3,3) for _ in range(3)];d=[rng.uniform(1,4) for _ in range(3)]
        add('extrude','extrude',box(p,d))
        add('revolve','revolve',cyl(p,rng.uniform(.3,1),rng.uniform(.5,2)))
        for op in ['fillet','chamfer']:add(op,op,box(p,d),radius=.1*min(d))
        add('holes','hole',box(p,d),b=cyl([p[0]+d[0]/2,p[1]+d[1]/2,p[2]-.2],.15*min(d[:2]),d[2]+.4))
        add('patterns','pattern',box(p,d),step=[d[0]+.5,0,0],count=rng.choice([2,3,4]))
    for i in range(3):add('step','step_roundtrip',box([i,-i,0],[1+i,2,3]))
    if split=='public':
        add('boxes','difference',box(),b=box([2,0,0]),regression='engine-path unit_disjoint')
        add('fillet','fillet',box(d=[40,30,10]),radius=2,regression='engine-path radius-2 fillet')
        add('step','step_import',box(),fixture='nist_ctc_01_asme1_ap242-e1.stp',regression='engine-path empty-success assembly traversal')
    out=Path(out) if out else ROOT/'corpus'/split;out.mkdir(parents=True,exist_ok=True)
    for c in cases:(out/(c['id']+'.json')).write_text(json.dumps(c,sort_keys=True)+'\n')
    print(split,len(cases))
if __name__=='__main__':
    generate('public',73129,52)
    generate('heldout',946271,17)
