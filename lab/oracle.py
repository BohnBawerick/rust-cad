"""Independent analytic values and integrals of emitted triangle coordinates."""
import math,itertools,collections

def analytic(c):
    a=c['a'];op=c['op'];p=a['origin']
    if a['kind']=='box':
        d=a['size'];v=math.prod(d);area=2*sum(d[i]*d[j] for i,j in [(0,1),(0,2),(1,2)]);cen=[p[i]+d[i]/2 for i in range(3)]
    else:
        r=a['radius'];h=a['height'];v=math.pi*r*r*h;area=2*math.pi*r*(r+h);cen=[p[0],p[1],p[2]+h/2]
    if op in ['difference','union','intersection'] and a['kind']=='box':
        b=c['b'];q=b['origin'];e=b['size']
        grid=[sorted(set([p[i],p[i]+d[i],q[i],q[i]+e[i]])) for i in range(3)]
        cells={};v=0.;area=0.;moment=[0.,0.,0.]
        for idx in itertools.product(*(range(len(g)-1) for g in grid)):
            mid=[(grid[i][idx[i]]+grid[i][idx[i]+1])/2 for i in range(3)]
            inside=lambda lo,sz:all(lo[i]<mid[i]<lo[i]+sz[i] for i in range(3))
            ia=inside(p,d);ib=inside(q,e)
            if {'difference':ia and not ib,'union':ia or ib,'intersection':ia and ib}[op]:
                ds=[grid[i][idx[i]+1]-grid[i][idx[i]] for i in range(3)];cv=math.prod(ds);cells[idx]=ds;v+=cv
                for i in range(3):moment[i]+=mid[i]*cv
        for idx,ds in cells.items():
            for axis in range(3):
                for side in [-1,1]:
                    nbr=list(idx);nbr[axis]+=side
                    if tuple(nbr) not in cells:area+=math.prod(ds[j] for j in range(3) if j!=axis)
        cen=[x/v for x in moment] if v else None
    elif op in ['difference','union','intersection']:
        b=c['b'];q=b['origin'];r=a['radius'];h=a['height'];dist=math.hypot(q[0]-p[0],q[1]-p[1]);theta=math.acos(min(1,dist/(2*r)))
        lens=2*r*r*theta-.5*dist*math.sqrt(max(0,4*r*r-dist*dist));iv=lens*h
        ic=[(p[0]+q[0])/2,(p[1]+q[1])/2,p[2]+h/2];bc=[q[0],q[1],q[2]+h/2]
        if op=='intersection':v=iv;area=2*lens+4*r*theta*h;cen=ic if v else None
        elif op=='union':cen=[(v*cen[j]+v*bc[j]-iv*ic[j])/(2*v-iv) for j in range(3)];v=2*v-iv;area=2*(2*math.pi*r*r-lens)+(4*math.pi*r-4*r*theta)*h
        else:
            cen=[(v*cen[j]-iv*ic[j])/(v-iv) for j in range(3)] if v-iv>1e-12 else None
            v-=iv;area=0 if v<1e-12 else 2*(math.pi*r*r-lens)+2*math.pi*r*h
    elif op in ['fillet','chamfer']:
        r=c['radius'];h=d[2]
        if op=='fillet':
            removed=(1-math.pi/4)*r*r*h;area-=2*(1-math.pi/4)*r*r+(2-math.pi/2)*r*h
            rc=r*((5/6-math.pi/4)/(1-math.pi/4))
        else:removed=.5*r*r*h;area-=r*r+(2-math.sqrt(2))*r*h;rc=r/3
        cen=[(v*cen[j]-removed*([p[0]+rc,p[1]+rc,p[2]+h/2][j]))/(v-removed) for j in range(3)];v-=removed
    elif op=='hole':
        b=c['b'];r=b['radius'];removed=math.pi*r*r*d[2];cc=[*b['origin'][:2],p[2]+d[2]/2]
        cen=[(v*cen[j]-removed*cc[j])/(v-removed) for j in range(3)];v-=removed;area+=2*math.pi*r*d[2]-2*math.pi*r*r
    elif op=='pattern':
        n=c['count'];v*=n;area*=n;cen=[cen[j]+(n-1)*c['step'][j]/2 for j in range(3)]
    if cen is not None and c.get('rotation'):
        t=c['rotation'];x,y,z=cen;cen=[math.cos(t)*x-math.sin(t)*y,math.sin(t)*x+math.cos(t)*y,z]
    return dict(volume=v,area=area,centroid=cen)

def mesh_metrics(out):
    pts=out['points'];faces=out['triangles'];vol=0.;area=0.;m=[0.,0.,0.];edges=collections.Counter();oriented=collections.Counter()
    ref=pts[0] if pts else [0.,0.,0.]
    ids={};point_ids=[]
    for p in pts:
        k=tuple(round(x,8) for x in p);point_ids.append(ids.setdefault(k,len(ids)))
    for f in faces:
        if len(set(f))!=3:raise ValueError('degenerate triangle indices')
        a,b,c=[[pts[i][j]-ref[j] for j in range(3)] for i in f]
        cross=lambda u,v:[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        cr=cross(b,c);dv=sum(a[j]*cr[j] for j in range(3))/6;vol+=dv
        for j in range(3):m[j]+=dv*(a[j]+b[j]+c[j])/4
        cr=cross([b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)]);area+=math.sqrt(sum(x*x for x in cr))/2
        for u,w in zip(f,f[1:]+f[:1]):
            u=point_ids[u];w=point_ids[w];edge=tuple(sorted([u,w]));edges[edge]+=1;oriented[edge]+=1 if u<w else -1
    return dict(volume=vol,area=area,centroid=[m[j]/vol+ref[j] for j in range(3)] if abs(vol)>1e-20 else None,
        mesh_closed=all(n==2 and oriented[e]==0 for e,n in edges.items()),mesh_vertices=len(ids),triangles=len(faces))

def verdict(c,out):
    if out.get('status')!='ok':return dict(pass_=False,reasons=[out.get('status','invalid_output')+':'+out.get('error','')])
    expected=analytic(c);actual=mesh_metrics(out);reasons=[]
    curved=c['group'] in ['cylinders','revolve','holes','fillet','chamfer']
    rel=.01 if curved else 1e-6
    for key in ['volume','area']:
        if not math.isfinite(actual[key]) or abs(actual[key]-expected[key])>max(1e-8,abs(expected[key])*rel):reasons.append(key)
    if expected['centroid'] is not None:
        if actual['centroid'] is None or any(not math.isfinite(v) for v in actual['centroid']):reasons.append('centroid')
        elif math.dist(actual['centroid'],expected['centroid'])>max(1e-7,abs(expected['volume'])**(1/3)*rel):reasons.append('centroid')
    if expected['volume']>1e-10:
        if not out['shells'] or not out['triangles']:reasons.append('empty_geometry')
        if not out['consistent']:reasons.append('geometric_consistency')
        if not actual['mesh_closed']:reasons.append('mesh_closure')
        for sh in out['shells']:
            if any(n!=2 or orient!=0 for n,orient in sh['edge_uses']):reasons.append('manifold_edge_uses')
            if sh['euler']>2 or sh['euler']%2:reasons.append('euler')
    elif out['shells'] or out['triangles']:reasons.append('expected_empty')
    return dict(pass_=not reasons,reasons=sorted(set(reasons)),expected=expected,actual=actual)
