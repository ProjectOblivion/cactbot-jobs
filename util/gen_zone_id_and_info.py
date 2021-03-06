#!/usr/bin/env python

import coinach
import csv
import csv_util
import json
import os
import re

# cactbot calls this "zone" largely because the id here is relative to the
# zone change event.  It corresponds to the TerritoryType.ID directly
# however, the name in ZoneId and the info in ZoneInfo contain information
# from other tables like PlaceName and TerritoryType, so it's not strictly
# about Territory.  Hence, "zone" as a short-to-type catch-all.
_ZONE_ID_OUTPUT_FILE = "zone_id.js"
_ZONE_INFO_OUTPUT_FILE = "zone_info.js"
_CONTENT_TYPE_OUTPUT_FILE = "content_type.js"

# name_key to territory_id mappings for locations with conflicts
known_ids = {
    "TheDiadem": 929,
}

# Notes: use rawexd here instead of exd to get place ids / territory ids
# instead of the lookups for PlaceName / TerritoryType that are not unique.
# The connections here are:
#   TerritoryType has Map, PlaceName, anonymous ContentFinderCondition (but not all have this)
#   ContentFinderCondition has Name, TerritoryType (but not all TerritoryType has CFC)
#   PlaceName has Name
#
# Name-finding Algorithm:
# Look up TerritoryType
# if it has a CFC: use that
# else if CFC has a TerritoryType that matches: use that
# else: use PlaceName


def make_territory_map(contents):
    inputs = ["#", 11, "PlaceName", "Name", "WeatherRate", "Map", "TerritoryIntendedUse"]
    outputs = [
        "territory_id",
        "cfc_id",
        "place_id",
        "name",
        "weather_rate",
        "map_id",
        "territory_intended_use",
    ]
    return csv_util.make_map(contents, inputs, outputs)


def make_place_name_map(contents):
    inputs = ["#", "Name"]
    outputs = ["place_id", "place_name"]
    return csv_util.make_map(contents, inputs, outputs)


def make_cfc_map(contents):
    inputs = ["#", "TerritoryType", "Name", "ContentType"]
    outputs = ["cfc_id", "territory_id", "name", "content_type_id"]
    return csv_util.make_map(contents, inputs, outputs)


# :eyes:
def make_map_map(contents):
    inputs = ["#", "SizeFactor", "Offset{X}", "Offset{Y}"]
    outputs = ["map_id", "size_factor", "offset_x", "offset_y"]
    return csv_util.make_map(contents, inputs, outputs)


def make_content_type_map(contents):
    inputs = ["#", "Name"]
    outputs = ["content_type_id", "name"]
    return csv_util.make_map(contents, inputs, outputs)


def print_error(header, what, map, key):
    print("%s %s: %s" % (header, what, json.dumps(map[key])))


def generate_name_data(territory_map, cfc_map, place_name_map):
    map = {}
    map["MatchAll"] = None
    territory_to_cfc_map = {}

    cfc_names = set()
    collision_names = set()

    # Build territory name to cfc id map.  Collisions have value None.
    territory_to_cfc = {}
    for cfc_id, cfc in cfc_map.items():
        territory_id = cfc["territory_id"]

        # Collision?
        if territory_id in territory_to_cfc:
            territory_to_cfc[territory_id] = None
        territory_to_cfc[territory_id] = cfc_id

    # First pass, find everything with a cfc name.
    # These take precedence over any later collisions.
    for territory_id, territory in territory_map.items():
        cfc_id = territory["cfc_id"]
        if cfc_id == "0":
            continue
        raw_name = cfc_map[cfc_id]["name"]
        name_key = csv_util.clean_name(raw_name)
        if not name_key:
            continue
        cfc_names.add(name_key)

    # Second pass, generate all the names, giving cfc names priority.
    for territory_id, territory in territory_map.items():
        cfc_id = territory["cfc_id"]
        place_id = territory["place_id"]
        place_name = place_name_map[place_id]["place_name"]
        territory_name = territory["name"]

        cfc_id_for_name = None

        is_town_zone = territory["territory_intended_use"] == "0"
        is_overworld_zone = territory["territory_intended_use"] == "1"

        if cfc_id != "0":
            cfc_id_for_name = cfc_id
            name_key = csv_util.clean_name(cfc_map[cfc_id]["name"])
        elif territory_id in territory_to_cfc and territory_to_cfc[territory_id]:
            cfc_id_for_name = territory_to_cfc[territory_id]
            name_key = csv_util.clean_name(cfc_map[cfc_id_for_name]["name"])
        elif is_town_zone or is_overworld_zone:
            # World zones like Middle La Noscea are not in CFC.
            name_key = csv_util.clean_name(place_name)
            # Names from ContentFinderCondition take precedence over
            # territory names.  There are some duplicates, such as
            # The Copied Factory version you can walk around in.
            if name_key in cfc_names:
                continue
        else:
            # TODO: add a verbose option
            # print_error("skipping", place_name, territory_map, territory_id)
            continue

        if not name_key:
            continue

        # If we've already seen this twice, ignore.
        if name_key in collision_names:
            print_error("collision", name_key, territory_map, territory_id)
            continue

        # If this is a collision with an existing name,
        # remove the old one.
        if name_key in map:
            collision_names.add(name_key)
            print_error("collision", name_key, territory_map, str(map[name_key]))
            print_error("collision", name_key, territory_map, territory_id)
            map.pop(name_key)
            continue

        territory_to_cfc_map[territory_id] = cfc_id_for_name
        if name_key in known_ids and known_ids[name_key] != int(territory_id):
            print_error("skipping", name_key, territory_map, territory_id)
            continue

        map[name_key] = int(territory_id)

    # map is what gets written to zone_id.js, but it's also useful to keep additional information
    # about where the name came from.
    return map, territory_to_cfc_map


def generate_zone_info(territory_map, cfc_map, map_map, territory_to_cfc_map, place_name_map):

    map = {}
    for territory_id in territory_to_cfc_map:
        output = {}
        map[territory_id] = output

        territory = territory_map[territory_id]
        place_id = territory["place_id"]
        place_name = place_name_map[place_id]["place_name"]

        output["weatherRate"] = int(territory["weather_rate"])

        cfc_id = territory_to_cfc_map[territory_id]
        if cfc_id == None:
            output["name"] = {"en": place_name}
        else:
            cfc = cfc_map[cfc_id]
            output["name"] = {"en": cfc["name"]}
            output["contentType"] = int(cfc["content_type_id"])

        map_id = territory["map_id"]
        if map_id in map_map:
            map_info = map_map[map_id]
            output["sizeFactor"] = int(map_info["size_factor"])
            output["offsetX"] = int(map_info["offset_x"])
            output["offsetY"] = int(map_info["offset_y"])
        else:
            print("missing map: %s" % territory_id)

    return map


def generate_content_type(content_type_map):
    map = {}
    for id, content_type in content_type_map.items():
        name = content_type["name"]
        if not name:
            continue
        map[csv_util.clean_name(name)] = int(id)
    return map


if __name__ == "__main__":
    # TODO: make an arg parser for non-default paths
    reader = coinach.CoinachReader(verbose=True)
    writer = coinach.CoinachWriter(verbose=True)

    territory_map = make_territory_map(reader.rawexd("TerritoryType"))
    place_name_map = make_place_name_map(reader.rawexd("PlaceName"))
    cfc_map = make_cfc_map(reader.rawexd("ContentFinderCondition"))
    map_map = make_map_map(reader.rawexd("Map"))

    name_data, territory_to_cfc_map = generate_name_data(territory_map, cfc_map, place_name_map)

    writer.write(
        os.path.join("resources", _ZONE_ID_OUTPUT_FILE),
        os.path.basename(os.path.abspath(__file__)),
        "ZoneId",
        name_data,
    )

    # TODO: get one cfc_map / territory_map per language and then we can translate ZoneId.
    # This would allow for auto-translating the raidboss config per-file.
    territory_info = generate_zone_info(
        territory_map, cfc_map, map_map, territory_to_cfc_map, place_name_map
    )
    writer.write(
        os.path.join("resources", _ZONE_INFO_OUTPUT_FILE),
        os.path.basename(os.path.abspath(__file__)),
        "ZoneInfo",
        territory_info,
    )

    content_type_map = make_content_type_map(reader.rawexd("ContentType"))
    writer.write(
        os.path.join("resources", _CONTENT_TYPE_OUTPUT_FILE),
        os.path.basename(os.path.abspath(__file__)),
        "ContentType",
        generate_content_type(content_type_map),
    )
