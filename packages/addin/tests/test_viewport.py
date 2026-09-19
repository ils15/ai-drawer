"""Camera geometry, reversible capture, validation, and PNG processing."""

import base64
import copy
import json
import math
import os
import struct
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch

import _fusion_test_bootstrap  # noqa: F401

from fusion_bridge import tool_surface, viewport
from lib import png_image


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def make_png(width, height, raw, color=6, depth=8):
    return (png_image.SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def read_unfiltered(png):
    header = struct.unpack('>IIBBBBB', png[16:29])
    position, data = 8, bytearray()
    while position < len(png):
        size = struct.unpack_from('>I', png, position)[0]
        if png[position+4:position+8] == b'IDAT':
            data.extend(png[position+8:position+8+size])
        position += size + 12
    return header[:2], zlib.decompress(data)


class PNGTests(unittest.TestCase):
    def test_all_five_filters_decode_to_same_pixels(self):
        first = bytes([10, 20, 30, 40, 50, 60, 70, 80])
        second = bytes([20, 40, 60, 80, 100, 120, 140, 160])
        filtered = [second, bytes([20,40,60,80,80,80,80,80]),
                    bytes([10,20,30,40,50,60,70,80]),
                    bytes([15,30,45,60,65,70,75,80]),
                    bytes([10,20,30,40,50,60,70,80])]
        for kind, encoded in enumerate(filtered):
            with self.subTest(filter=kind):
                source = make_png(2, 2, b'\0' + first + bytes([kind]) + encoded)
                dims, decoded = read_unfiltered(png_image.transform(source))
                self.assertEqual(dims, (2, 2))
                self.assertEqual(decoded, b'\0' + first + b'\0' + second)
                dims, cropped = read_unfiltered(png_image.transform(source, (1, 1, 1, 1)))
                self.assertEqual((dims, cropped), ((1, 1), b'\0' + second[4:]))

    def test_transparency_composited_without_altering_opaque_pixels(self):
        source = make_png(3, 1, b'\0' + bytes([255,0,0,0, 200,100,0,128, 1,2,3,255]))
        _, raw = read_unfiltered(png_image.transform(source, background=(0, 0, 255)))
        self.assertEqual(raw, b'\0' + bytes([0,0,255,255, 100,50,127,255, 1,2,3,255]))

    def test_rgb_crop(self):
        source = make_png(2, 1, b'\0\x01\x02\x03\x04\x05\x06', color=2)
        self.assertEqual(read_unfiltered(png_image.transform(source, (1,0,1,1))), ((1,1), b'\0\x04\x05\x06'))

    def test_crop_preserves_color_metadata(self):
        source = make_png(2, 1, b'\0\x01\x02\x03\x04\x05\x06', color=2)
        metadata = chunk(b'sRGB', b'\0') + chunk(b'gAMA', struct.pack('>I', 45455))
        source = source[:33] + metadata + source[33:]
        result = png_image.transform(source, (1, 0, 1, 1))
        self.assertEqual(result[33:33 + len(metadata)], metadata)
        self.assertEqual(read_unfiltered(result), ((1, 1), b'\0\x04\x05\x06'))

    def test_rejects_corruption_oversize_and_bad_crop(self):
        source = make_png(1, 1, b'\0\x01\x02\x03\xff')
        for invalid in (source[:-2], b'garbage', source[:35]+b'broken'+source[41:],
                        make_png(100000,100000,b''), make_png(1,1,b'\0'*100),
                        make_png(1,1,b'\0'*9,depth=16)):
            with self.subTest(data=invalid[:30]), self.assertRaises(ValueError):
                png_image.transform(invalid)
        for crop in ((-1,0,1,1),(0,0,2,1),(0,0,0,1),(0.5,0,1,1)):
            with self.assertRaises(ValueError):
                png_image.transform(source,crop)


class Vec:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


class Camera:
    def __init__(self):
        self.eye, self.target, self.upVector = Vec(0,0,10), Vec(), Vec(0,1,0)
        self.cameraType = 0
        self.perspectiveAngle = math.pi / 4
        self.isSmoothTransition = False
        self.isFitView = False
        self.extents = (20,10)

    def getExtents(self):
        return True, *self.extents

    def setExtents(self, width, height):
        self.extents = (width, height)
        return True


class Viewport:
    def __init__(self):
        self._camera = Camera()
        self.width, self.height = 800, 600
        self.saved = []
        self.fail_save = False
        self.fail_refresh_once = False
        self.png = make_png(2, 1, b'\0' + bytes([255,0,0,255, 0,0,0,0]))

    @property
    def camera(self):
        return copy.deepcopy(self._camera)

    @camera.setter
    def camera(self, value):
        self._camera = copy.deepcopy(value)
        if value.isFitView:
            self._camera.extents = (10,5)
            self._camera.isFitView = False
        if hasattr(value, 'viewOrientation'):
            self._camera.eye = Vec(10,0,0)
            del self._camera.viewOrientation

    def refresh(self):
        if self.fail_refresh_once:
            self.fail_refresh_once = False
            raise RuntimeError('refresh failed')
        return True

    def saveAsImageFile(self, path, width, height):
        self.saved.append((path, width, height))
        if self.fail_save == 'exception':
            raise RuntimeError('export failed')
        if self.fail_save:
            return False
        with open(path,'wb') as handle:
            handle.write(self.png)
        return True

    def saveAsImageFileWithOptions(self, options):
        self.options = options
        return self.saveAsImageFile(options.filename, options.width, options.height)


class ViewportTests(unittest.TestCase):
    def setUp(self):
        self.vp = Viewport()
        self.app = SimpleNamespace(activeViewport=self.vp)
        values = {
            'CameraTypes': SimpleNamespace(
                OrthographicCameraType=0,
                PerspectiveCameraType=1,
                PerspectiveWithOrthoFacesCameraType=2,
            ),
            'ViewOrientations': SimpleNamespace(
                **{name: i for i, name in enumerate(viewport.VIEW_NAMES.values())}
            ),
            'Point3D': SimpleNamespace(create=Vec), 'Vector3D': SimpleNamespace(create=Vec),
            'SaveImageFileOptions': SimpleNamespace(create=lambda path: SimpleNamespace(filename=path)),
        }
        for name,value in values.items():
            patcher=patch.object(viewport.adsk.core,name,value,create=True)
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher=patch.object(viewport.adsk.core.Application,'get',return_value=self.app)
        self.addCleanup(patcher.stop)
        patcher.start()

    def result(self, response):
        self.assertFalse(response.get('isError'),response)
        return json.loads(response['content'][0]['text'])

    def test_snapshot_round_trip_and_orthographic_zoom(self):
        before=self.result(viewport.get_viewport({}))
        self.assertEqual(before['units'],{'length':'cm','angle':'degrees'})
        after=self.result(viewport.set_viewport({'zoom':2}))
        self.assertEqual(after['camera']['extents'],{'width':10,'height':5})
        restored=self.result(viewport.set_viewport({'camera':before['camera']}))
        self.assertEqual(before,restored)

    def test_perspective_zoom_changes_distance_not_angle(self):
        self.vp._camera.cameraType=1
        after=self.result(viewport.set_viewport({'zoom':2}))['camera']
        self.assertEqual(after['eye'],{'x':0,'y':0,'z':5})
        self.assertEqual(after['perspective_angle'],45)
        self.assertNotIn('extents',after)
        self.assertEqual(self.result(viewport.set_viewport({'camera':after}))['camera'],after)

    def test_orbit_preserves_target_distance_and_orthogonal_up(self):
        after=self.result(viewport.set_viewport({'orbit':{'yaw':90,'pitch':30,'roll':45}}))['camera']
        eye=tuple(after['eye'].values())
        up=tuple(after['up_vector'].values())
        self.assertAlmostEqual(math.hypot(*eye),10)
        self.assertAlmostEqual(math.hypot(*up),1)
        self.assertAlmostEqual(sum(x*y for x,y in zip(eye,up,strict=True)),0)
        self.assertAlmostEqual(eye[0],10*math.cos(math.pi/6))
        self.assertAlmostEqual(eye[1],-5)
        self.assertEqual(after['target'],{'x':0,'y':0,'z':0})

    def test_pan_and_fit_then_zoom(self):
        after=self.result(viewport.set_viewport({'fit':True,'pan':{'x':3,'y':4},'zoom':2}))['camera']
        self.assertEqual(after['target'],{'x':3,'y':4,'z':0})
        self.assertEqual(after['eye'],{'x':3,'y':4,'z':10})
        self.assertEqual(after['extents'],{'width':5,'height':2.5})

    def test_invalid_controls_never_change_camera(self):
        before=self.result(viewport.get_viewport({}))
        invalid=[{'zoom':0},{'zoom':True},{'orbit':{'yaw':float('nan')}}, {'pan':{'x':float('inf')}},
                 {'view':'invalid'},{'projection':'invalid'},{'fit':'yes'},
                 {'camera':before['camera'],'zoom':2}]
        pose=copy.deepcopy(before['camera'])
        pose['eye']=pose['target']
        invalid.append({'camera':pose})
        pose=copy.deepcopy(before['camera'])
        pose['up_vector']={'x':0,'y':0,'z':1}
        invalid.append({'camera':pose})
        for args in invalid:
            with self.subTest(args=args):
                self.assertTrue(viewport.set_viewport(args)['isError'])
                self.assertEqual(self.result(viewport.get_viewport({})),before)

    def test_camera_restored_after_failed_change(self):
        before=self.result(viewport.get_viewport({}))
        self.vp.fail_refresh_once=True
        self.assertTrue(viewport.set_viewport({'zoom':2})['isError'])
        self.assertEqual(self.result(viewport.get_viewport({})),before)

    def test_original_capture_defaults_and_native_size_supported(self):
        for args,dims in (({},(800,600)),({'width':0,'height':0},(0,0))):
            result=viewport.capture(args)
            self.assertFalse(result['isError'],result)
            self.assertEqual(base64.b64decode(result['content'][0]['data']),self.vp.png)
            path,width,height=self.vp.saved[-1]
            self.assertEqual((width,height),dims)
            self.assertFalse(os.path.exists(path))

    def test_capture_restores_camera_and_cleans_file_on_all_export_outcomes(self):
        for fail in (False,True,'exception'):
            with self.subTest(failure=fail):
                before=self.result(viewport.get_viewport({}))
                self.vp.fail_save=fail
                result=viewport.capture({'view':'top','fit':True})
                self.assertEqual(result['isError'],bool(fail))
                self.assertEqual(self.result(viewport.get_viewport({})),before)
                self.assertFalse(os.path.exists(self.vp.saved[-1][0]))

    def test_background_crop_and_antialias_options(self):
        result=viewport.capture({'width':2,'height':1,'background':'#123456','anti_aliasing':False,'crop':{'x':1,'y':0,'width':1,'height':1}})
        self.assertFalse(result['isError'],result)
        self.assertTrue(self.vp.options.isBackgroundTransparent)
        self.assertFalse(self.vp.options.isAntiAliased)
        png=base64.b64decode(result['content'][0]['data'])
        self.assertEqual(read_unfiltered(png),((1,1),b'\0\x12\x34\x56\xff'))
        result=viewport.capture({'background':'transparent'})
        self.assertEqual(base64.b64decode(result['content'][0]['data']),self.vp.png)

    def test_invalid_capture_arguments_do_not_render(self):
        for args in ({'width':-1},{'height':1.5},{'width':True},{'width':8192,'height':8192},
                     {'background':'red'},{'anti_aliasing':'no'},{'crop':{'x':0,'y':0,'width':900,'height':600}}):
            with self.subTest(args=args):
                self.assertTrue(viewport.capture(args)['isError'])
        self.assertEqual(self.vp.saved,[])

    def test_absent_viewport_returns_tool_errors(self):
        self.app.activeViewport=None
        for function in (viewport.get_viewport,viewport.set_viewport,viewport.capture):
            self.assertTrue(function({})['isError'])

    def test_schema_and_implementation_have_same_views_and_projections(self):
        self.assertEqual(set(tool_surface.STANDARD_VIEWS),set(viewport.VIEW_NAMES))
        self.assertEqual(set(tool_surface.PROJECTIONS),set(viewport.PROJECTIONS))


if __name__=='__main__':
    unittest.main()
