"""Element names of SheetMetal features must be reproducible.

For each feature a small model is built. Then every element must have a
mapped name that has a source tag (no ':H:' and no ';D<n>' counters), the
names must not change on a plain recompute, and a parameter change that keeps
the topology must keep all names.

Run with FreeCAD's Test framework, or unittest in the FreeCAD console.
"""
import re
import unittest

import FreeCAD
import Part
import Sketcher

HAS_TOPONAMING = hasattr(Part.Shape, "ElementMap")
V = FreeCAD.Vector
Q = FreeCAD.Units.Quantity
T = 1.5


def _names(obj):
    """Indexed name -> mapped name."""
    return {v: k for k, v in obj.Shape.ElementMap.items()}


def _weak(obj):
    """Mapped names without a source tag, or with a ;D duplicate counter.

    The trailing ';:H,<type>' of every name and the internal step of
    FreeCAD's own offset ('OFS;:H:') are ignored.
    """
    weak = []
    for name in obj.Shape.ElementMap:
        n = re.sub(r";:H,[FEV]$", "", name).replace("OFS;:H:", "OFS;")
        if ":H:" in n or ":H," in n or re.search(r";D\d", n):
            weak.append(name)
    return weak


def _edgeAt(obj, x=None, y=None, z=None):
    for i, e in enumerate(obj.Shape.Edges):
        bb = e.BoundBox
        if all(v is None or (abs(lo - v) < 1e-6 and abs(hi - v) < 1e-6)
               for lo, hi, v in ((bb.XMin, bb.XMax, x), (bb.YMin, bb.YMax, y),
                                 (bb.ZMin, bb.ZMax, z))):
            return "Edge%d" % (i + 1)
    raise RuntimeError("edge not found")


def _faceWith(obj, normal, pred=lambda f: True):
    best = None
    for i, f in enumerate(obj.Shape.Faces):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
        if (n - normal).Length < 1e-6 and pred(f):
            if best is None or f.Area > obj.Shape.Faces[best].Area:
                best = i
    if best is None:
        raise RuntimeError("face not found")
    return "Face%d" % (best + 1)


@unittest.skipUnless(HAS_TOPONAMING, "needs FreeCAD with toponaming support")
class TestToponamingFeatures(unittest.TestCase):

    def setUp(self):
        self.doc = FreeCAD.newDocument("ToponamingFeatures")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    # ---- model helpers ----

    def _plate(self):
        """Body with a parametric 100 x 60 sketch and a BaseBend plate."""
        from SheetMetalBaseCmd import SMBaseBend

        self.body = body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = sk = body.newObject("Sketcher::SketchObject", "BaseSketch")
        pts = [V(x, y, 0) for x, y in ((-50, -30), (50, -30), (50, 30), (-50, 30))]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            sk.addGeometry(Part.LineSegment(a, b))
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        for c in (("Horizontal", 0), ("Horizontal", 2), ("Vertical", 1), ("Vertical", 3)):
            sk.addConstraint(Sketcher.Constraint(*c))
        sk.addConstraint(Sketcher.Constraint("Symmetric", 0, 1, 1, 2, -1, 1))
        sk.renameConstraint(sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 100)),
                            "Width")
        sk.renameConstraint(sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 60)),
                            "Depth")
        self.doc.recompute()
        base = body.newObject("PartDesign::FeaturePython", "BaseBend")
        SMBaseBend(base, sk)
        base.Thickness = T
        self.doc.recompute()
        return base

    def _bend(self, base, edges, **props):
        from SheetMetalCmd import SMBendWall

        bend = self.body.newObject("PartDesign::FeaturePython", "Bend")
        SMBendWall(bend, base, edges)
        for k, v in props.items():
            setattr(bend, k, v)
        self.doc.recompute()
        return bend

    def _box(self):
        """Hollow box, open top, 60 x 40 x 30, wall 1.5, as a plain Part feature."""
        outer = Part.makeBox(60, 40, 30)
        inner = Part.makeBox(60 - 2 * T, 40 - 2 * T, 30, V(T, T, T))
        box = self.doc.addObject("Part::Feature", "Box")
        box.Shape = outer.cut(inner)
        self.doc.recompute()
        return box

    def _width(self, value):
        return lambda: self.sketch.setDatum("Width", Q("%g mm" % value))

    # ---- the check ----

    def _check(self, obj, change):
        self.doc.recompute()
        # Names settle once after creation (a duplicate postfix is dropped);
        # this happens without tagging too and is not checked here.
        for o in self.doc.Objects:
            if o.TypeId != "Sketcher::SketchObject" and hasattr(o, "Shape"):
                o.touch()
        self.doc.recompute()
        obj.touch()
        self.doc.recompute()
        self.assertTrue(obj.isValid(), obj.getStatusString())

        shape = obj.Shape
        total = len(shape.Faces) + len(shape.Edges) + len(shape.Vertexes)
        before = _names(obj)
        self.assertEqual(len(before), total, "elements without a mapped name")
        self.assertEqual(_weak(obj), [], "names without a source tag")

        obj.touch()
        self.doc.recompute()
        self.assertEqual(_names(obj), before, "names changed on recompute")

        change()
        self.doc.recompute()
        self.assertTrue(obj.isValid(), obj.getStatusString())
        self.assertEqual(len(obj.Shape.Faces) + len(obj.Shape.Edges) + len(obj.Shape.Vertexes),
                         total, "test change altered the topology")
        self.assertEqual(set(_names(obj).values()), set(before.values()),
                         "names changed with the parameter")

    # ---- features ----

    def test_bend_without_gaps(self):
        base = self._plate()
        bend = self._bend(base, [_edgeAt(base, x=50, z=T)])
        self._check(bend, lambda: self.sketch.setDatum("Depth", Q("70 mm")))

    def test_hem(self):
        from SheetMetalHem import SMHem

        base = self._plate()
        hem = self.body.newObject("PartDesign::FeaturePython", "Hem")
        SMHem(hem, base, [_edgeAt(base, x=50, z=T)])
        self._check(hem, self._width(120))

    def test_base_shape(self):
        from SheetMetalBaseShapeCmd import SMBaseShape

        for shapeType in ("L-Shape", "Hat"):
            with self.subTest(shapeType=shapeType):
                obj = self.doc.addObject("PartDesign::FeaturePython", "BaseShape")
                SMBaseShape(obj)
                obj.shapeType = shapeType
                self._check(obj, lambda: setattr(obj, "length", 120))

    def test_fold(self):
        from SheetMetalFoldCmd import SMFoldWall

        base = self._plate()
        top = _faceWith(base, V(0, 0, 1))
        line = self.body.newObject("Sketcher::SketchObject", "FoldLine")
        line.AttachmentSupport = [(base, top)]
        line.MapMode = "FlatFace"
        self.doc.recompute()
        a, b = (line.Placement.inverse().multVec(V(20, y, T)) for y in (-40, 40))
        line.addGeometry(Part.LineSegment(V(a.x, a.y, 0), V(b.x, b.y, 0)))
        self.doc.recompute()
        fold = self.body.newObject("PartDesign::FeaturePython", "Fold")
        SMFoldWall(fold, base, [top], line)
        self._check(fold, lambda: setattr(fold, "angle", 60))

    def test_extruded_cutout(self):
        from ExtrudedCutout import ExtrudedCutout

        base = self._plate()
        cut = self.body.newObject("Sketcher::SketchObject", "CutSketch")
        cut.addGeometry(Part.Circle(V(-20, 10, 0), V(0, 0, 1), 5))
        radius = cut.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        cut.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, -20))
        cut.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 10))
        self.doc.recompute()
        obj = self.body.newObject("PartDesign::FeaturePython", "Cutout")
        ExtrudedCutout(obj, cut, [base, _faceWith(base, V(0, 0, 1))])
        self._check(obj, lambda: cut.setDatum(radius, Q("7 mm")))

    def test_wrapped_cutout(self):
        from SketchOnSheetMetalCmd import SMSketchOnSheet

        base = self._plate()
        bend = self._bend(base, [_edgeAt(base, x=50, z=T)])
        sk = self.body.newObject("Sketcher::SketchObject", "WrapSketch")
        sk.AttachmentSupport = [(base, _faceWith(base, V(0, 0, 1)))]
        sk.MapMode = "FlatFace"
        self.doc.recompute()
        pts = [sk.Placement.inverse().multVec(V(x, y, T))
               for x, y in ((40, -5), (56, -5), (56, 5), (40, 5))]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            sk.addGeometry(Part.LineSegment(V(a.x, a.y, 0), V(b.x, b.y, 0)))
        self.doc.recompute()
        obj = self.body.newObject("PartDesign::FeaturePython", "WrappedCutout")
        SMSketchOnSheet(obj, bend, _faceWith(bend, V(0, 0, 1), lambda f: f.CenterOfMass.z > 1), sk)
        self._check(obj, lambda: self.sketch.setDatum("Depth", Q("70 mm")))

    def test_corner_relief(self):
        from SheetMetalCornerReliefCmd import SMCornerRelief

        base = self._plate()
        bend = self._bend(base, [_edgeAt(base, y=-30, z=T), _edgeAt(base, x=50, z=T)],
                          AutoMiter=True)
        obj = self.body.newObject("PartDesign::FeaturePython", "CornerRelief")
        SMCornerRelief(obj, bend, [_edgeAt(bend, y=-30, z=0), _edgeAt(bend, x=50, z=0)])
        self._check(obj, lambda: setattr(obj, "Size", 4))

    def test_junction(self):
        from SheetMetalJunction import SMJunction

        box = self._box()
        obj = self.doc.addObject("Part::FeaturePython", "Junction")
        SMJunction(obj, box, [_edgeAt(box, x=0, y=0)])
        self._check(obj, lambda: setattr(obj, "gap", 3))

    # ---- selection changes: a wall's names must stay with its edge ----

    def _wallFace(self, obj, side):
        """Largest planar face of the wall on `side` of the 100 x 60 plate."""
        sel = {"front": lambda n, c: n.y < -0.99 and c.y < -30.5,
               "right": lambda n, c: n.x > 0.99 and c.x > 50.5,
               "back": lambda n, c: n.y > 0.99 and c.y > 30.5}[side]
        best = None
        for i, f in enumerate(obj.Shape.Faces):
            if f.Surface.TypeId != "Part::GeomPlane":
                continue
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            if sel(n, f.CenterOfMass) and (best is None or f.Area > obj.Shape.Faces[best].Area):
                best = i
        self.assertIsNotNone(best, "no %s wall" % side)
        return best

    def _assertOnFace(self, sketch, obj, index):
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        f = obj.Shape.Faces[index]
        n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
        self.assertLess((sketch.Placement.Rotation.multVec(V(0, 0, 1)) - n).Length, 1e-6,
                        "sketch is not on the expected face")
        self.assertLess(abs((sketch.Placement.Base - f.CenterOfMass).dot(n)), 1e-6,
                        "sketch is not on the expected face")

    def _attach(self, obj, index):
        sk = self.body.newObject("Sketcher::SketchObject", "OnWall")
        sk.AttachmentSupport = [(obj, "Face%d" % (index + 1))]
        sk.MapMode = "FlatFace"
        self.doc.recompute()
        return sk

    def test_bend_selection_changes(self):
        cases = [  # (edges before, edges after, wall with the attached sketch)
            (["front", "right", "back"], ["right", "back"], "back"),
            (["front", "right", "back"], ["front", "back"], "back"),
            (["right", "back"], ["front", "right", "back"], "back"),
            (["front", "back"], ["back", "front"], "front"),
        ]
        for before, after, side in cases:
            with self.subTest(before=before, after=after):
                if hasattr(self, "body"):
                    FreeCAD.closeDocument(self.doc.Name)
                    self.doc = FreeCAD.newDocument("ToponamingFeatures")
                base = self._plate()
                edge = {"front": _edgeAt(base, y=-30, z=T), "right": _edgeAt(base, x=50, z=T),
                        "back": _edgeAt(base, y=30, z=T)}
                bend = self._bend(base, [edge[s] for s in before])
                for o in (base, bend):
                    o.touch()
                self.doc.recompute()
                sk = self._attach(bend, self._wallFace(bend, side))
                bend.baseObject = (base, [edge[s] for s in after])
                self.doc.recompute()
                self._assertOnFace(sk, bend, self._wallFace(bend, side))

    def test_base_shape_type_change(self):
        """L-Shape -> U-Shape adds a -Y wall; the +Y wall must keep its names."""
        from SheetMetalBaseShapeCmd import SMBaseShape

        self.body = self.doc.addObject("PartDesign::Body", "Body")
        obj = self.body.newObject("PartDesign::FeaturePython", "BaseShape")
        SMBaseShape(obj)
        obj.shapeType = "L-Shape"
        self.doc.recompute()
        obj.touch()
        self.doc.recompute()

        def plusYWall():
            best = None
            for i, f in enumerate(obj.Shape.Faces):
                if f.Surface.TypeId != "Part::GeomPlane":
                    continue
                n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
                if n.y > 0.99 and (best is None or f.CenterOfMass.y > obj.Shape.Faces[best].CenterOfMass.y
                                   or (abs(f.CenterOfMass.y - obj.Shape.Faces[best].CenterOfMass.y) < 1e-6
                                       and f.Area > obj.Shape.Faces[best].Area)):
                    best = i
            return best

        sk = self._attach(obj, plusYWall())
        obj.shapeType = "U-Shape"
        self.doc.recompute()
        self._assertOnFace(sk, obj, plusYWall())
