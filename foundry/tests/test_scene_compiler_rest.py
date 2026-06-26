from scene_compiler import rest_offset


def test_rest_offset_centered_origin():
    # GLB whose origin is at its center, half-height 0.5 -> min_y = -0.5
    assert rest_offset(-0.5) == 0.5


def test_rest_offset_base_origin():
    # GLB already authored with base at origin -> min_y = 0 -> no shift
    assert rest_offset(0.0) == 0.0
