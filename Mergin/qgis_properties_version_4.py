import defusedxml.ElementTree as ET
from xml.etree.ElementTree import Element
from typing import Dict
import zipfile


def read_xml_tree_from_qgz(qgz_path: str) -> Element:
    qgs_filename = next(
        (name for name in zipfile.ZipFile(qgz_path).namelist() if name.endswith(".qgs")),
        None,
    )

    if qgs_filename is None:
        raise ValueError(f"No .qgs file found inside {qgz_path}")

    with zipfile.ZipFile(qgz_path, "r") as input_zip_file:
        entries = {name: input_zip_file.read(name) for name in input_zip_file.namelist()}

    return ET.fromstring(entries[qgs_filename])


def is_qgis_version_4(qgz_file: str) -> bool:
    root = read_xml_tree_from_qgz(qgz_file)

    version = root.attrib.get("version", "")
    if not version.startswith("4."):
        return False

    return True


def parse_properties(element, prefix="") -> Dict:
    """Recursively parse nested <properties> elements into a flat dict with path keys."""
    result = {}

    for child in element:
        if child.tag != "properties":
            continue

        name = child.attrib.get("name", "")
        key = f"{prefix}/{name}" if prefix else name
        prop_type = child.attrib.get("type")

        if prop_type is not None:
            if prop_type == "QStringList":
                result[key] = [v.text for v in child.findall("value")]
            else:
                result[key] = child.text
        else:
            result.update(parse_properties(child, prefix=key))

    return result


def read_mergin_properties(qgz_file: str) -> Dict:
    root = read_xml_tree_from_qgz(qgz_file)

    version = root.attrib.get("version", "")
    if not version.startswith("4."):
        return {}

    mergin_elem = root.find(".//properties[@name='Mergin']")
    if mergin_elem is None:
        return {}

    props = parse_properties(mergin_elem)

    return props
