use monstertruck_assembly::assy::*;
use monstertruck_io::step::load::{convert::*, *};
use monstertruck_meshing::prelude::*;
type MeshedCShell = monstertruck_topology::compress::CompressedShell<Point3, PolylineCurve<Point3>, Option<PolygonMesh>>;
pub fn step_to_mesh(table: &Table) -> Vec<MeshedCShell> {
    let assy = table.step_assy().unwrap();

    let node_map = |ProductEntity {
                        shape: indices,
                        attrs: name,
                    }: &ProductEntity| {
        let shape = indices
            .iter()
            .filter_map(|idx| {
                let shells = if let Some(step_solid) = table.manifold_solid_brep.get(idx) {
                    table
                        .to_compressed_solid(step_solid)
                        .map_err(|err| eprintln!("failed to convert solid: {err}"))
                        .ok()?
                        .boundaries
                } else {
                    let step_shells = table.shell_based_surface_model.get(idx)?;
                    table
                        .to_compressed_shells(step_shells)
                        .map_err(|err| eprintln!("failed to convert shells: {err}"))
                        .ok()?
                };
                let meshed_shells = shells
                    .into_iter()
                    .map(|shell| {
                        let bdd = shell_bounding_box(&shell);
                        let tol = f64::max(bdd.diameter() * 0.001, TOLERANCE);
                        shell.robust_triangulation(tol)
                    })
                    .collect::<Vec<_>>();
                Some(meshed_shells)
            })
            .collect::<Vec<_>>();
        NodeEntity {
            shape,
            attrs: name.clone(),
        }
    };
    let edge_map = |EdgeEntity { matrix: trans, .. }: &AssembleEntity| EdgeEntity {
        matrix: Matrix4::try_from(trans).unwrap(),
        attrs: (),
    };

    let meshed_assy = assy.par_map(node_map, edge_map);

    meshed_assy
        .top_nodes()
        .flat_map(|top| meshed_assy.paths_iter(top.index()))
        .flat_map(|path| {
            let matrix = path.matrix();
            let shapes = path.terminal_node().shape().clone();
            shapes.into_iter().flatten().map(move |mut shell| {
                shell.vertices.iter_mut().for_each(|v| {
                    *v = matrix.transform_point(*v);
                });
                shell.edges.iter_mut().for_each(|edge| {
                    edge.curve.transform_by(matrix);
                });
                shell.faces.iter_mut().for_each(|face| {
                    if let Some(surface) = face.surface.as_mut() {
                        surface.transform_by(matrix);
                    }
                });
                shell
            })
        })
        .collect()
}

/// Computes bounding box from vertices, edge curves, and bounded surface corners.
fn shell_bounding_box<C, S>(shell: &monstertruck_topology::compress::CompressedShell<Point3, C, S>) -> BoundingBox<Point3>
where
    C: ParametricCurve3D + BoundedCurve,
    S: ParametricSurface3D, {
    let mut bdd: BoundingBox<Point3> = shell.vertices.iter().collect();
    for edge in &shell.edges {
        let (t0, t1) = edge.curve.range_tuple();
        // Sample 5 points per edge to capture curvature extent.
        for i in 0..=4 {
            let t = t0 + (t1 - t0) * i as f64 / 4.0;
            bdd.push(edge.curve.subs(t));
        }
    }
    for face in &shell.faces {
        let (urange, vrange) = face.surface.try_range_tuple();
        if let (Some((u0, u1)), Some((v0, v1))) = (urange, vrange) {
            bdd.push(face.surface.subs(u0, v0));
            bdd.push(face.surface.subs(u1, v0));
            bdd.push(face.surface.subs(u0, v1));
            bdd.push(face.surface.subs(u1, v1));
            bdd.push(face.surface.subs((u0 + u1) / 2.0, (v0 + v1) / 2.0));
        }
    }
    bdd
}

