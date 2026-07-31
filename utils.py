import bpy

def safe_set_socket_value(socket, value):
    if not socket or not hasattr(socket, "default_value"):
        return
    try:
        dv = socket.default_value
        if hasattr(dv, "__len__"):
            length = len(dv)
            if isinstance(value, (int, float)):
                socket.default_value = (value,) * length
            else:
                val_tuple = tuple(value)
                if len(val_tuple) >= length:
                    socket.default_value = val_tuple[:length]
                else:
                    socket.default_value = val_tuple + (0.0,) * (length - len(val_tuple))
        else:
            if isinstance(value, (int, float)):
                socket.default_value = value
            else:
                socket.default_value = float(value[0])
    except Exception:
        pass

def safe_set_vrm_prop(obj, attr, value):
    if not obj or not hasattr(obj, attr):
        return
    try:
        prop = getattr(obj, attr)
        if hasattr(prop, "__len__"):
            length = len(prop)
            if isinstance(value, (int, float)):
                prop[:] = [value] * length
            else:
                val_list = list(value)
                if len(val_list) >= length:
                    prop[:] = val_list[:length]
                else:
                    prop[:] = val_list + [0.0] * (length - len(val_list))
        else:
            setattr(obj, attr, value)
    except Exception:
        pass

def safe_set_vrm_tex(prop_obj, image_obj):
    if not prop_obj or not image_obj:
        return
    try:
        if hasattr(prop_obj, "source"):
            try:
                prop_obj.source = image_obj
            except TypeError:
                pass
        if hasattr(prop_obj, "value"):
            try:
                prop_obj.value = image_obj
            except TypeError:
                try:
                    prop_obj.value = image_obj.name
                except Exception:
                    pass
    except Exception:
        pass

def create_separate_color_node(nodes):
    try:
        return nodes.new("ShaderNodeSepColor")
    except Exception:
        try:
            return nodes.new("ShaderNodeSeparateColor")
        except Exception:
            return nodes.new("ShaderNodeSeparateRGB")

def get_channel_output(sep_node, channel_char):
    if channel_char in sep_node.outputs:
        return sep_node.outputs[channel_char]
    idx = {"R": 0, "G": 1, "B": 2}[channel_char]
    return sep_node.outputs[idx]

def create_mix_color_node(nodes):
    try:
        mix_node = nodes.new("ShaderNodeMix")
        mix_node.data_type = 'COLOR'
        mix_node.blend_type = 'MIX'
        return mix_node
    except Exception:
        mix_node = nodes.new("ShaderNodeMixRGB")
        mix_node.blend_type = 'MIX'
        return mix_node

def link_mix_inputs(links, mix_node, factor_out, color_a_out, color_b_out, target_in):
    if mix_node.bl_idname == "ShaderNodeMix":
        links.new(factor_out, mix_node.inputs["Factor"])
        links.new(color_a_out, mix_node.inputs["A"])
        links.new(color_b_out, mix_node.inputs["B"])
        links.new(mix_node.outputs["Result"], target_in)
    else:
        links.new(factor_out, mix_node.inputs["Fac"])
        links.new(color_a_out, mix_node.inputs["Color1"])
        links.new(color_b_out, mix_node.inputs["Color2"])
        links.new(mix_node.outputs["Color"], target_in)
