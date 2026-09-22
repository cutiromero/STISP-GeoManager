from pathlib import Path

from django.test import SimpleTestCase

from apps.raster.services.categorical import (
    categorical_class_entries,
    is_categorical_metadata,
)
from apps.raster.services.importer import gdalwarp_cog_command


class CategoricalMetadataTests(SimpleTestCase):
    def test_categorical_cog_ignores_existing_overviews_and_uses_nearest(self):
        command = gdalwarp_cog_command(
            source_path=Path("source.tif"),
            processed_path=Path("processed.tif"),
            resampling="nearest",
            nodata=255,
        )

        self.assertIn("nearest", command)
        self.assertIn("OVERVIEWS=IGNORE_EXISTING", command)
        self.assertIn("WARP_RESAMPLING=NEAREST", command)
        self.assertIn("OVERVIEW_RESAMPLING=NEAREST", command)
        self.assertIn("UNIFIED_SRC_NODATA=YES", command)
        self.assertIn("INIT_DEST=NO_DATA", command)
        self.assertEqual(command[command.index("-srcnodata") + 1], "255")
        self.assertEqual(command[command.index("-dstnodata") + 1], "255")

    def test_reads_thematic_rat_labels_and_transparent_colors(self):
        metadata = {
            "bands": [
                {
                    "band": 1,
                    "type": "Byte",
                    "rat": {
                        "tableType": "thematic",
                        "fieldDefn": [
                            {"name": "Value", "usage": 5},
                            {"name": "ClassName", "usage": 2},
                            {"name": "Red", "usage": 6},
                            {"name": "Green", "usage": 7},
                            {"name": "Blue", "usage": 8},
                            {"name": "Alpha", "usage": 9},
                        ],
                        "row": [[0, "背景", 10, 20, 30, 0]],
                    },
                }
            ]
        }

        self.assertTrue(is_categorical_metadata(metadata))
        self.assertEqual(
            categorical_class_entries(metadata),
            [{"value": 0, "label": "背景", "color": "#0a141e00"}],
        )

    def test_uses_color_table_for_declared_class_codes(self):
        entries = [[0, 0, 0, 255] for _ in range(6)]
        entries[5] = [59, 121, 183, 255]
        metadata = {
            "metadata": {"": {"CLASS_CODES": "5=水体"}},
            "bands": [{"band": 1, "colorTable": {"entries": entries}}],
        }

        self.assertEqual(
            categorical_class_entries(metadata),
            [{"value": 5, "label": "水体", "color": "#3b79b7"}],
        )
