# Robot Model Builder: OBJ to URDF

Choose **Model Builder** in Studio. This editor creates robot links and joints from mesh components, with a motion preview and an exportable URDF/mesh bundle. STEP import is not implemented; export an OBJ from CAD first. This is a mesh-based model editor, not a solid CAD engine.

## First example

1. Import `examples/model-builder/two-link-arm.obj` with **Metres** selected. It contains a base and arm.
2. Select the arm in the component list or click it in the viewport. Choose **Create link from selection**, rename the new link `arm_link`, and keep `base_link` as parent.
3. Set the joint to **revolute**. Set pivot XYZ to `0.1, 0, 0.15`, frame roll/pitch/yaw to `0, 0, 0` and axis to `0, 0, 1`.
4. Move the `arm_link` position slider. Its mesh should rotate around that pivot. Reset to zero when finished.
5. Confirm scale/orientation, then **Validate URDF**. Mass is intentionally unspecified. If you enter measured mass, the editor generates an approximate uniform-box inertia.
6. **Export URDF bundle** downloads a ZIP with `robot.urdf`, per-link STL meshes, `robot-builder.json` and an explanation of approximations. Extract all files together so relative mesh paths remain valid.

## Components and links

OBJ object/group labels are preserved. With the split option enabled, disconnected vertex components within a label become separate selectable parts. This is topology-based splitting: duplicated seam vertices can create extra parts, and welded geometry cannot be split into mechanical components automatically. Merge disconnected pieces by assigning them to the same link. There is no manual face-cutting tool yet.

Every part belongs to exactly one rigid link. Select several parts and create a link, or assign them to an existing active link. Add empty sensor frames for mount locations without geometry. Merge a child link into its parent to undo unnecessary mechanical separation. Regrouping clears mass on affected links because the previous mass may no longer describe them.

The importer accepts polygon OBJ geometry, including negative vertex/normal indices and simple planar concave polygons. It preserves corner normals and smoothing groups, but ignores materials, textures and texture coordinates. Unsupported/invalid faces produce line-numbered errors. Limits are 4 MiB per OBJ, 30,000 source vertices, 60,000 source normals, 20,000 triangles and 256 components; simplify larger CAD exports before import.

The preview uses depth-tested surface rendering with **Smooth shading** enabled and **Wireframe** disabled by default. Imported normals take priority. Without normals, area-weighted smoothing joins coincident vertices within a part when faces differ by at most 45 degrees and share a smoothing group; explicit `s off` keeps faces flat. Turn off smooth shading to inspect facets, or enable wireframe to inspect triangles. Browsers without WebGL show a basic preview. These display controls do not change geometry: an angular silhouette still needs a finer CAD mesh export. Normals survive editable-model saves and joint motion; exported STL files contain face normals only.

## Scale and coordinate frames

OBJ coordinates do not establish trustworthy physical scale. Choose metres, centimetres or millimetres before import, or enter **metres per OBJ unit** afterward. Alternatively select components and calibrate one of their axis-aligned X/Y/Z bounding dimensions against a known measurement. This is bounding-box calibration, not a point-to-point measuring tool.

Link pivots are entered in the imported model's zero-pose coordinates, in metres. Frame roll/pitch/yaw is in radians. Joint axes are expressed in the child link frame and normalized for export. The pivot is the link frame origin; it need not coincide with the geometry centre. Use **Centre pivot on link geometry** as a starting point, then adjust it to the actual shaft or hinge.

The root link frame becomes the exported URDF origin; its orientation defines robot forward/up. Geometry is transformed into each link's local frame and joint origins are calculated relative to their parents. The viewport stays in imported-model coordinates, so exported root coordinates can differ by a global rigid transform. Rescaling also scales pivot positions and prismatic travel limits. Revolute/prismatic limits must include the imported zero pose.

Fixed, continuous, revolute and prismatic joints are supported. The editor validates a single connected tree, unique link names, assignments, finite coordinates, valid axes and limits. Closed mechanical loops, floating joints and mimic joints are not supported.

## Physics and Studio integration limits

Collision geometry is an optional axis-aligned box in the link frame, not an exact mesh or convex decomposition. If mass is supplied, centre of mass and inertia are estimated from a uniform bounding box; these are not CAD-derived or measured mass properties. Omitted mass/inertia is reported during validation/export. A generated URDF is not a qualified physics model until these properties are checked.

Use **Use in robot setup** to hand the model directly to the guided setup preview, or open the exported ZIP in Robot setup. Supported four-wheel robots can create a built-in or Webots simulation project with the visual meshes, normals and component colors preserved. Save project embeds these assets; manual mesh copying is unnecessary. See [the model-to-simulation guide](MODEL_TO_SIMULATION.md) for geometry requirements and the included mesh rover. Arbitrary articulated robots and exact CAD physics are not supported.

**Save editable model** writes a complete JSON model with geometry and editor settings. Reopen it using **Open editable model**, or use `robot-builder.json` from the ZIP. Closing/reopening the dialog preserves the model for the current Studio tab session; reloading the browser does not. Save before refreshing. Camera angles, selection and motion-slider positions are temporary preview state.

## Tests

`python tests/run_all.py` covers OBJ grouping, concave triangulation, invalid faces, kinematic transforms, link-local mesh export, bundle round-trips and invalid joint trees. The optional `python tests/browser_model_builder.py` checks the actual editor workflow with Playwright/Edge.
