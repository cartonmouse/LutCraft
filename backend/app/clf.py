"""Strict inspection for bundled, self-contained photo conversion CLFs.

This is not a general CLF upload endpoint. Only the Matrix/Exponent/LUT3D
subset emitted by our offline converter is accepted; external references,
entities and arbitrary processing nodes are rejected before OCIO sees them.
"""
import hashlib
import json
import math
import xml.etree.ElementTree as ET

from .errors import AppError

MAX_BYTES = 10 * 1024 * 1024
NS = "{http://www.smpte-ra.org/ns/2136-1/2024}"


def inspect_clf(data):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def tag(node):
        require(node.tag.startswith(NS), "XML 命名空间无效")
        return node.tag[len(NS):]

    def array(node, expected):
        require(len(node) == 1 and tag(node[0]) == "Array", "缺少唯一 Array")
        a = node[0]
        require(set(a.attrib) == {"dim"} and len(a) == 0, "Array 属性无效")
        dims = [int(v) for v in a.attrib["dim"].split()]
        require(dims == expected, "Array 尺寸无效")
        values = [float(v) for v in (a.text or "").split()]
        require(len(values) == math.prod(expected), "Array 数值数量无效")
        require(all(math.isfinite(v) and abs(v) <= 3.4e38 for v in values), "Array 包含无效数值")
        return values

    try:
        require(0 < len(data) <= MAX_BYTES, "文件超过 10 MiB 或为空")
        text = data.decode("utf-8")
        require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(), "禁止 XML 实体或外部声明")
        root = ET.fromstring(text)
        require(tag(root) == "ProcessList", "缺少 ProcessList")
        require(set(root.attrib) <= {"compCLFversion", "id", "name"} and root.get("compCLFversion") == "3", "需要 CLF 3")
        names = [tag(n) for n in root]
        require(names in (["Exponent", "Exponent", "LUT3D", "Exponent", "Exponent"],
                          ["Exponent", "Matrix", "Exponent", "LUT3D", "Exponent", "Matrix", "Exponent"]), "不支持的转换链")
        canonical, size, table_range = [], None, None
        for node in root:
            kind = tag(node)
            require(node.get("inBitDepth") == "32f" and node.get("outBitDepth") == "32f", "需要 32f 浮点处理")
            if kind == "Exponent":
                require(set(node.attrib) == {"inBitDepth", "outBitDepth", "style"}, "Exponent 属性无效")
                style = node.get("style")
                require(style in {"monCurveFwd", "monCurveRev", "basicFwd"}, "不支持的 Exponent")
                require(len(node) == 1 and tag(node[0]) == "ExponentParams" and len(node[0]) == 0, "ExponentParams 无效")
                p = node[0].attrib
                require(set(p) == ({"exponent"} if style == "basicFwd" else {"exponent", "offset"}), "ExponentParams 属性无效")
                params = {k: float(v) for k, v in p.items()}
                require(all(math.isfinite(v) for v in params.values()) and 0.1 <= params["exponent"] <= 10, "指数无效")
                require(0 <= params.get("offset", 0) <= .9, "offset 无效")
                canonical.append([kind, style, params])
            elif kind == "Matrix":
                require(set(node.attrib) == {"inBitDepth", "outBitDepth"}, "Matrix 属性无效")
                canonical.append([kind, array(node, [3, 3])])
            else:
                require(set(node.attrib) == {"inBitDepth", "outBitDepth", "interpolation"} and node.get("interpolation") == "tetrahedral", "LUT3D 需要四面体插值")
                require(len(node) == 1, "LUT3D Array 无效")
                dims = [int(v) for v in node[0].get("dim", "").split()]
                require(len(dims) == 4 and 2 <= dims[0] <= 65, "LUT3D 尺寸超限")
                size = dims[0]
                values = array(node, [size, size, size, 3])
                table_range = [min(values), max(values)]
                canonical.append([kind, size, values])
        require(root[0].get("style") == "monCurveFwd" and root[-1].get("style") == "monCurveRev", "需要完整 sRGB 编解码")
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return {"title": root.get("name", ""), "lut_type": "CLF", "grid_size": size,
                "data_rows": size ** 3, "domain_min": [0.0] * 3, "domain_max": [1.0] * 3,
                "output_value_range": None, "embedded_lut_value_range": table_range,
                "operations": names, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "mapping_sha256": digest}
    except (ValueError, UnicodeError, ET.ParseError, OverflowError) as exc:
        raise AppError("clf_format", f"照片转换 CLF 无效：{exc}。") from exc
