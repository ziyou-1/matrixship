# -*- coding: utf-8 -*-
"""本地 protobuf → dict 转换器（drop-in 替代已失修的 protobuf_to_dict 包）。

背景：老的 `protobuf_to_dict` 第三方库用 `field.label == LABEL_REPEATED` 判断重复字段，
而 protobuf 5.x/7.x 的 upb C 后端已移除 FieldDescriptor 实例上的 `.label` 属性，会抛
`'google._upb._message.FieldDescriptor' object has no attribute 'label'`，导致私信
(create_conversation / send_message 的响应解析) 直接失败。

这里用现代 protobuf 都支持的 `field.is_repeated` 判断重复，并正确处理 map 字段，
保留字段原始类型(int 仍是 int、bytes 仍是 bytes)与 snake_case 字段名，输出结构与旧
`protobuf_to_dict` 一致，下游按 key 取值的代码无需改动。
"""
from google.protobuf.descriptor import FieldDescriptor


def _is_repeated(field):
    ir = getattr(field, 'is_repeated', None)
    if ir is not None:
        return ir
    # 兼容极老的 protobuf：回退到 label 判断
    try:
        return field.label == FieldDescriptor.LABEL_REPEATED
    except Exception:
        return False


def _is_map(field):
    try:
        mt = field.message_type
        return (field.type == FieldDescriptor.TYPE_MESSAGE
                and mt is not None
                and mt.GetOptions().map_entry)
    except Exception:
        return False


def _convert_value(field, value):
    if field.type == FieldDescriptor.TYPE_MESSAGE:
        return protobuf_to_dict(value)
    return value


def protobuf_to_dict(pb):
    result = {}
    for field, value in pb.ListFields():
        if _is_map(field):
            val_field = field.message_type.fields_by_name.get('value')
            if val_field is not None and val_field.type == FieldDescriptor.TYPE_MESSAGE:
                result[field.name] = {k: protobuf_to_dict(v) for k, v in value.items()}
            else:
                result[field.name] = {k: v for k, v in value.items()}
            continue
        if _is_repeated(field):
            result[field.name] = [_convert_value(field, v) for v in value]
        else:
            result[field.name] = _convert_value(field, value)
    return result
