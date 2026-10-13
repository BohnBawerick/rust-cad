mod step;
use monstertruck_modeling::*;
use monstertruck_meshing::prelude::*;
use monstertruck_io::step::save::{CompleteStepDisplay, StepHeaderDescriptor, StepModel};
use serde_json::{Value, json};
use std::{collections::{HashMap, HashSet}, fs, panic::{catch_unwind, AssertUnwindSafe}};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn xyz(v: &Value) -> [f64; 3] { [v[0].as_f64().unwrap(),v[1].as_f64().unwrap(),v[2].as_f64().unwrap()] }
fn num(v: &Value, key: &str, default: f64) -> f64 {v[key].as_f64().unwrap_or(default)}
fn shape(v: &Value) -> Result<Solid> {
    let p=xyz(&v["origin"]);
    let origin=Point3::new(p[0],p[1],p[2]);
    if v["kind"]=="box" {
        let d=xyz(&v["size"]);
        let a=builder::vertex(origin);
        let e=builder::extrude(&a,Vector3::new(d[0],0.,0.));
        let f=builder::extrude(&e,Vector3::new(0.,d[1],0.));
        Ok(builder::extrude(&f,Vector3::new(0.,0.,d[2])))
    } else {
        let r=num(v,"radius",1.); let h=num(v,"height",1.);
        let vertex=builder::vertex(origin+Vector3::new(r,0.,0.));
        let wire=builder::revolve(&vertex,origin,Vector3::unit_z(),builder::SweepAngle::Closed,4);
        let face=builder::try_attach_plane(&[wire])?;
        Ok(builder::extrude(&face,Vector3::new(0.,0.,h)))
    }
}
fn run(c: &Value) -> Result<Value> {
    if c["op"]=="step_import" {
        let table=monstertruck_io::step::load::Table::from_step(&fs::read_to_string("/fixture.stp")?)?;
        let meshes=step::step_to_mesh(&table);
        let triangles:usize=meshes.iter().map(|s|s.to_polygon().tri_faces().len()).sum();
        return Ok(json!({"status":"ok","input_solids":table.manifold_solid_brep.len(),"import_shells":meshes.len(),"import_triangles":triangles}));
    }
    let angle=Rad(num(c,"rotation",0.));
    let a=builder::rotated(&shape(&c["a"])?,Point3::origin(),Vector3::unit_z(),angle);
    let tol=num(c,"boolean_tol",0.05);
    let mode=c["op"].as_str().ok_or("missing op")?;
    let solids: Vec<Solid> = match mode {
        "difference" | "union" | "intersection" | "hole" => {
            let b=builder::rotated(&shape(&c["b"])?,Point3::origin(),Vector3::unit_z(),angle);
            vec![match mode {
                "union"=>monstertruck_solid::or(&a,&b,tol)?,
                "intersection"=>monstertruck_solid::and(&a,&b,tol)?,
                _=>monstertruck_solid::difference(&a,&b,tol)?
            }]
        },
        "fillet" | "chamfer" => {
            let mut shell=a.boundaries()[0].clone(); let p=xyz(&c["a"]["origin"]);
            let edge=shell.edge_iter().find(|e| {let v=e.front().point();let w=e.back().point();
                (v.x-p[0]).abs()<1e-8 && (w.x-p[0]).abs()<1e-8 && (v.y-p[1]).abs()<1e-8 && (w.y-p[1]).abs()<1e-8
            }).ok_or("edge absent")?;
            let opts=FilletOptions::constant(num(c,"radius",0.1)).with_profile(if mode=="fillet" {FilletProfile::Round} else {FilletProfile::Chamfer});
            fillet_edges(&mut shell,&[edge],Some(&opts))?;
            vec![Solid::try_new(vec![shell])?]
        },
        "revolve" => {
            let p=xyz(&c["a"]["origin"]); let r=num(&c["a"],"radius",1.);let h=num(&c["a"],"height",1.);
            let axis=Point3::new(p[0],p[1],p[2]);
            let v0=builder::vertex(axis); let v1=builder::vertex(axis+Vector3::new(r,0.,0.));
            let v2=builder::vertex(axis+Vector3::new(r,0.,h));let v3=builder::vertex(axis+Vector3::new(0.,0.,h));
            let wire:Wire=vec![builder::line(&v3,&v2),builder::line(&v2,&v1),builder::line(&v1,&v0)].into();
            let shell=builder::revolve_wire(&wire,axis,Vector3::unit_z(),builder::SweepAngle::Closed,4);
            vec![Solid::try_new(vec![shell])?]
        },
        "pattern" => {
            let step=xyz(&c["step"]); let count=c["count"].as_u64().unwrap();
            (0..count).map(|i|builder::translated(&a,Vector3::new(step[0],step[1],step[2])*(i as f64))).collect()
        },
        "extrude" | "primitive" | "step_roundtrip" => vec![a],
        _=>return Err("unsupported operation".into())
    };
    let mut shells=Vec::new();let mut all_points=Vec::new();let mut all_triangles=Vec::new();let mut step=String::new();
    let mut consistent=true;let mut roundtrip=Value::Null;
    for solid in &solids {
        consistent &= catch_unwind(AssertUnwindSafe(||solid.is_geometric_consistent())).unwrap_or(false);
        for shell in solid.boundaries() {
            let mut edges=HashMap::new();let mut vertices=HashSet::new();let mut face_cells=0i64;
            for face in shell.iter() {
                face_cells+=2-face.boundaries().len() as i64;
                for wire in face.boundaries() {for e in wire.iter() {
                    let uses=edges.entry(e.id()).or_insert((0,0));uses.0+=1;uses.1+=if e.orientation(){1}else{-1};
                    vertices.insert(e.front().id());vertices.insert(e.back().id());
                }}
            }
            shells.push(json!({"vertices":vertices.len(),"edges":edges.len(),"faces":shell.len(),"face_cells":face_cells,
                "edge_uses":edges.values().map(|x|[x.0,x.1]).collect::<Vec<_>>(),"euler":vertices.len() as i64-edges.len() as i64+face_cells}));
        }
        if !solid.boundaries().is_empty() {
            let mesh=solid.triangulation(num(c,"mesh_tol",0.005)).collect_option().ok_or("mesh omitted face")?.to_polygon();
            let base=all_points.len();
            all_points.extend(mesh.positions().iter().map(|p|[p.x,p.y,p.z]));
            all_triangles.extend(mesh.tri_faces().iter().map(|t|[base+t[0].pos,base+t[1].pos,base+t[2].pos]));
            if mode=="step_roundtrip" {
                step=CompleteStepDisplay::new(StepModel::from(&solid.compress()),StepHeaderDescriptor::default()).to_string();
                let table=monstertruck_io::step::load::Table::from_step(&step)?;
                let mut points=Vec::new();let mut triangles=Vec::new();let mut lossless=true;
                for shell in table.shell.values() {
                    let (cs,report)=table.to_compressed_shell_reported(shell)?;
                    lossless &= report.is_lossless();
                    let ms=cs.robust_triangulation(num(c,"mesh_tol",0.002));
                    if ms.faces.iter().any(|f|f.surface.is_none()) {return Err("roundtrip omitted face".into());}
                    let poly=ms.to_polygon();let base=points.len();
                    points.extend(poly.positions().iter().map(|p|[p.x,p.y,p.z]));
                    triangles.extend(poly.tri_faces().iter().map(|t|[base+t[0].pos,base+t[1].pos,base+t[2].pos]));
                }
                roundtrip=json!({"points":points,"triangles":triangles,"lossless":lossless});
            }
        }
    }
    Ok(json!({"status":"ok","shells":shells,"consistent":consistent,"points":all_points,"triangles":all_triangles,"roundtrip":roundtrip,"step_bytes":step.len()}))
}
fn main() {
    std::panic::set_hook(Box::new(|_|{}));
    let result=catch_unwind(AssertUnwindSafe(||->Result<Value>{
        let path=std::env::args().nth(1).ok_or("provide case JSON")?;
        let case:Value=serde_json::from_str(&fs::read_to_string(path)?)?;
        run(&case)
    }));
    let out=match result {Ok(Ok(v))=>v,Ok(Err(e))=>json!({"status":"error","error":e.to_string()}),Err(_)=>json!({"status":"panic"})};
    println!("{out}");
}
