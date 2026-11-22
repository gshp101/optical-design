"""Search stock lenses by properties and insert one into a design (lensforge.stock).

Run from the project folder:  python examples/stock_lens_demo.py [CATALOG.ZMF or part.zmx ...]

Without arguments only the generic "LensForge Demo" parts are searched. Pass vendor files you
downloaded (a Zemax .ZMF lens catalog, or a part's .zmx from Thorlabs, Edmund Optics, Newport, ...)
to search them too; lib.save() would remember them for the desktop app and later scripts.
"""

import sys

import lensforge as lf

lib = lf.StockLibrary.default()
for path in sys.argv[1:]:
    print(f"imported {len(lib.import_file(path))} lens(es) from {path}")

hits = lib.search(kind="plano-convex", efl=(40, 110), diameter=(20, 30), glass="BK7")
print(f"\n{len(hits)} plano-convex BK7 lens(es), f 40..110 mm, diameter 20..30 mm:")
for x in hits:
    print(f"  {x.part:20s} {x.vendor:16s} f = {x.efl:8.3f}  D = {x.diameter:6.2f}  CT = {x.thickness:5.2f}")

# a 100 mm achromat (closest focal length first) behind a stop; reverse=True would turn it round
part = lib.search(kind="cemented doublet", efl=100)[0]
lens = lf.OpticalSystem("Stock achromat")
lens.set_aperture("EPD", 10)
lens.set_fields([0, 1, 2])
lens.set_wavelengths([0.4861, 0.5876, 0.6563], primary=1)
lens.add_surface(thickness=5, stop=True)
lf.insert_stock_lens(lens, part, at=2, reverse=False)
print(f"\n{part.label} inserted after the stop:")
print(lens.prescription())
print(f"EFL {lens.paraxial().efl:.4f} mm")
