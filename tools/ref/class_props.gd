# Dumps every class's property names (inherited included) from the engine's ClassDB, for tscn_lint.py.
# Run: Godot --headless --script res://tools/ref/class_props.gd  (writes tools/ref/class_props.json)
extends SceneTree

func _make(cls: String):
	# only scene/resource classes matter for .tscn; skip editor, XR and server-side singletons
	if not (ClassDB.is_parent_class(cls, "Node") or ClassDB.is_parent_class(cls, "Resource")):
		return null
	if not ClassDB.can_instantiate(cls) or cls.begins_with("Editor") or cls.contains("Server") or cls.contains("XR") \
			or cls in ["Engine", "OS", "Time", "Input", "IP", "ResourceLoader", "ResourceSaver", "ClassDB", "Marshalls",
				"JavaClassWrapper", "JavaScriptBridge", "Geometry2D", "Geometry3D", "GDExtensionManager",
				"ResourceUID", "WorkerThreadPool", "ThemeDB", "TranslationServer", "ProjectSettings"]:
		return null
	return ClassDB.instantiate(cls)


func _init() -> void:
	var out := {}
	for cls in ClassDB.get_class_list():
		var names := []
		var plist: Array = ClassDB.class_get_property_list(cls)
		# an instance also reports dynamic storage properties (_get_property_list): AnimationPlayer.libraries,
		# TileMap.format / tile_data, PhysicalBone3D.bone_name, Curve._data ...
		var inst = _make(cls)
		if inst != null:
			plist = inst.get_property_list()
			if inst is Node:
				inst.free()
		for p in plist:
			if p.usage & (PROPERTY_USAGE_GROUP | PROPERTY_USAGE_SUBGROUP | PROPERTY_USAGE_CATEGORY):
				continue
			names.append(p.name)
		out[cls] = names
	var f := FileAccess.open("res://tools/ref/class_props.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(out))
	f.close()
	print("classes: %d" % out.size())
	quit()
