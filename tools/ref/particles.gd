# Prints a particles cheat sheet straight from the engine: enum values that .tscn files store as plain ints, and the
# exact .tscn text Godot writes for a GPUParticles2D with trails, a scale curve, a box emission and a sub-emitter.
# Run: Godot --headless --script res://tools/ref/particles.gd > tools/ref/particles.txt (drop the banner line)
# Node names and numbers are deliberately neutral, not taken from any benchmark task.
extends SceneTree

const ENUMS = {
	"ParticleProcessMaterial": ["EmissionShape", "SubEmitterMode"],
	"GPUParticles2D": ["DrawOrder"],
	"GPUParticles3D": ["DrawOrder"],
}


func _init() -> void:
	for cls in ENUMS:
		for e in ENUMS[cls]:
			var parts := []
			for c in ClassDB.class_get_enum_constants(cls, e):
				parts.append("%s=%d" % [c, ClassDB.class_get_integer_constant(cls, c)])
			print("%s.%s: %s" % [cls, e, ", ".join(parts)])

	var root := Node2D.new()
	root.name = "Main"
	var rain := GPUParticles2D.new()
	rain.name = "Drops"
	var splash := GPUParticles2D.new()
	splash.name = "Impact"
	root.add_child(rain)
	root.add_child(splash)
	rain.owner = root
	splash.owner = root

	var mat := ParticleProcessMaterial.new()
	mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	mat.emission_box_extents = Vector3(100, 20, 1)
	mat.sub_emitter_mode = ParticleProcessMaterial.SUB_EMITTER_AT_COLLISION
	mat.sub_emitter_amount_at_collision = 2
	var curve := Curve.new()
	curve.add_point(Vector2(0, 0.5))
	curve.add_point(Vector2(1, 1))
	var ct := CurveTexture.new()
	ct.curve = curve
	mat.scale_curve = ct
	mat.scale_max = 2.0
	mat.gravity = Vector3.ZERO
	rain.process_material = mat
	rain.sub_emitter = rain.get_path_to(splash)
	rain.trail_enabled = true
	rain.trail_lifetime = 0.3
	rain.collision_base_size = 3.0

	var ps := PackedScene.new()
	ps.pack(root)
	var path := "user://particles_ref.tscn"
	ResourceSaver.save(ps, path)
	print("--- .tscn written by Godot (box emission, sub-emitter at collision, scale curve, trails) ---")
	print(FileAccess.get_file_as_string(path))
	root.free()
	quit()
