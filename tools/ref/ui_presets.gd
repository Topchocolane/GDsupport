# Prints, for every Control layout preset, the .tscn property lines the editor writes (anchors + grow direction).
# Anchors come from Control.set_anchors_and_offsets_preset(); grow direction mirrors Control::set_grow_direction_preset
# in scene/gui/control.cpp (4.6-stable), which is not bound to scripts.
# Run: Godot --headless --script res://tools/ref/ui_presets.gd > tools/ref/ui.txt
extends SceneTree

const NAMES = ["Top Left", "Top Right", "Bottom Left", "Bottom Right", "Center Left", "Center Top", "Center Right",
	"Center Bottom", "Center", "Left Wide", "Top Wide", "Right Wide", "Bottom Wide", "VCenter Wide", "HCenter Wide",
	"Full Rect"]
const ANCHORS = ["anchor_left", "anchor_top", "anchor_right", "anchor_bottom"]
# GrowDirection per preset, copied from control.cpp: BEGIN=0, END=1, BOTH=2
const H_GROW = [1, 0, 1, 0, 1, 2, 0, 2, 2, 1, 2, 0, 2, 2, 2, 2]
const V_GROW = [1, 1, 0, 0, 2, 1, 2, 0, 2, 2, 1, 2, 0, 2, 2, 2]


func _init() -> void:
	for i in NAMES.size():
		var c := Control.new()
		c.set_anchors_and_offsets_preset(i)
		var parts := ["layout_mode = 1", "anchors_preset = %d" % i]
		for p in ANCHORS:
			var v: float = c.get(p)
			if v != 0.0:
				parts.append("%s = %s" % [p, var_to_str(v)])
		# grow_* = 1 (End) is the default and is not written to the .tscn
		if H_GROW[i] != 1:
			parts.append("grow_horizontal = %d" % H_GROW[i])
		if V_GROW[i] != 1:
			parts.append("grow_vertical = %d" % V_GROW[i])
		print("%s: %s" % [NAMES[i], "; ".join(parts)])
		c.free()
	quit()
