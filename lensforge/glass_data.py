"""Built-in glass data.

Sellmeier (formula 2) coefficients from manufacturer data sheets / standard
references.  C coefficients are in um^2.  Catalog nd/vd are included so tests
can verify each entry.
"""

from .materials import Glass, GlassCatalog
from .schott_catalog import SCHOTT_INQUIRY, SCHOTT_PREFERRED

# Current SCHOTT catalog (preferred + inquiry glasses), see schott_catalog.py.
# name: (B1, B2, B3, C1, C2, C3, nd, vd)
_SCHOTT = {**SCHOTT_PREFERRED, **SCHOTT_INQUIRY}

# Obsolete Schott glasses (no longer in the current catalog), kept for legacy
# designs.  Sellmeier coefficients as in _SCHOTT, plus the catalog wavelength
# range (um).  Source: Zemax SCHOTT.AGF (2018 release for SF15, the 2008
# release with obsolete glasses for the rest).  FK51 and PK51A carry the same
# coefficients as their N- successors in that catalog.
# name: (B1, B2, B3, C1, C2, C3, nd, vd, lambda_min, lambda_max)
_SCHOTT_LEGACY = {
    "SF15":    (1.53925927, 0.247620926, 1.03816409, 0.0119307961, 0.0556077536, 116.416747, 1.69895, 30.07, 0.37, 2.5),
    "SF58":    (1.92184332, 0.552191937, 1.11643502, 0.0149262604, 0.0614139252, 123.450367, 1.917613, 21.51, 0.334, 2.325),
    "BAK2":    (1.01662154, 0.319903051, 0.937232995, 0.00592383763, 0.0203828415, 113.118417, 1.53996, 59.71, 0.28, 2.5),
    "FK5":     (0.844309338, 0.344147824, 0.910790213, 0.00475111955, 0.0149814849, 97.8600293, 1.48749, 70.41, 0.27, 2.5),
    "FK51":    (0.971247817, 0.216901417, 0.904651666, 0.00472301995, 0.0153575612, 168.68133, 1.486561, 84.47, 0.28, 2.5),
    "FK52":    (1.01571114, 0.169998431, 0.805158532, 0.00515884949, 0.0173380788, 158.603308, 1.486052, 81.80, 0.334, 2.325),
    "FK54":    (0.745320416, 0.302330101, 1.01885, 0.00358171563, 0.0122884773, 213.01745, 1.437000, 90.70, 0.334, 2.325),
    "PK51A":   (1.15610775, 0.153229344, 0.785618966, 0.00585597402, 0.0194072416, 140.537046, 1.528554, 76.98, 0.30, 2.5),
    "KZFS1":   (1.36618048, 0.182049028, 0.864314609, 0.00873165063, 0.0389834096, 62.9392443, 1.613099, 44.34, 0.334, 2.325),
    "LAK21":   (1.22718116, 0.420783743, 1.01284843, 0.00602075682, 0.0196862889, 88.4370099, 1.640495, 60.10, 0.334, 2.325),
    "LASF18A": (2.19336604, 0.332590474, 1.69849859, 0.0121930864, 0.0532519989, 106.8531, 1.913482, 32.36, 0.334, 2.325),
    "F3":      (1.32797322, 0.205862833, 0.904336126, 0.00977102802, 0.0463606329, 107.863739, 1.612931, 37.04, 0.334, 2.325),
    "F4":      (1.33905825, 0.205224318, 0.897859758, 0.00992220114, 0.0470000918, 107.93675, 1.616592, 36.63, 0.32, 2.5),
    "KF3":     (1.15615178, 0.102116759, 0.927164575, 0.00789264815, 0.0345076496, 113.531069, 1.514540, 54.70, 0.334, 2.325),
    "SF12":    (1.39867348, 0.238403762, 1.03604466, 0.0103415646, 0.0492696913, 118.327782, 1.648310, 33.84, 0.334, 2.325),
    "SK1":     (1.23997939, 0.308829519, 1.03366266, 0.00676460788, 0.0233830716, 114.585882, 1.610250, 56.71, 0.334, 2.325),
    "FN11":    (1.41572926, 0.143334227, 1.27299252, 0.0103749731, 0.0568803594, 119.664491, 1.620962, 36.18, 0.334, 2.325),
    "SSK1":    (1.42691045, 0.141195647, 0.986004821, 0.00831214602, 0.0334369911, 109.701359, 1.617201, 53.91, 0.334, 2.325),
    "SSKN5":   (1.59222659, 0.103520774, 1.05174016, 0.00920284626, 0.0423530072, 106.927374, 1.658440, 50.88, 0.334, 2.325),
}

# Obsolete glasses with no published Sellmeier data, given as Schott formula 1
# fits (A0..A5, n^2 = A0 + A1 w^2 + A2 w^-2 + A3 w^-4 + A4 w^-6 + A5 w^-8) to the
# Buchdahl coefficients of Robb, Appl. Opt. 24, 1864 (1985), which tabulates the
# 1983 Schott catalog.  Visible only (0.40-0.70 um, error ~2e-5).
# name: (A0, A1, A2, A3, A4, A5, nd, vd, lambda_min, lambda_max)
_SCHOTT_VISIBLE_FIT = {
    "LAF10": (3.096574518, -0.010314296118, 0.031832947849, -0.00040449276558, 9.7177497238e-05, 0.0,
              1.78443, 43.91, 0.40, 0.70),
    "LAF21": (3.115807562, -0.010521792700, 0.030196360600, -0.00043161217200, 8.3208374300e-05, 0.0,
              1.78831, 47.42, 0.40, 0.70),
    "SSK4": (2.566464692, -0.0068299445754, 0.01862828506, -0.00028897342523, 4.721963281e-05, 0.0,
             1.61765, 55.17, 0.40, 0.70),
    "SF61": (2.938461641, -0.0069783217138, 0.043366659385, -0.00018744609362, 0.00022040759375, 0.0,
             1.75084, 27.54, 0.40, 0.70),
    "SK52": (2.63231277, -0.0073444274177, 0.019518992965, -0.00031627135582, 4.7235109505e-05, 0.0,
             1.63854, 55.54, 0.40, 0.70),
    "SF01": (2.84637663, -0.00731513567, 0.038866284016, -0.00020819418331, 0.00018400233538, 0.0,
             1.72022, 29.35, 0.40, 0.70),
    "BALF51": (2.429322751, -0.0061727964311, 0.017614280382, -0.00025290310649, 4.8052742705e-05, 0.0,
               1.57393, 52.12, 0.40, 0.70),
}

# Crystals and other materials: Sellmeier with C given as resonance wavelength (um)
_MISC = {
    # name: (B1, B2, B3, L1, L2, L3, nd, vd)
    "F_SILICA": (0.6961663, 0.4079426, 0.8974794, 0.0684043, 0.1162414, 9.896161, 1.45846, 67.82),
    "CAF2":     (0.5675888, 0.4710914, 3.8484723, 0.050263605, 0.1003909, 34.649040, 1.43385, 94.99),
    "SAPPHIRE": (1.4313493, 0.65054713, 5.3414021, 0.0726631, 0.1193242, 18.028251, 1.76817, 72.31),
    "MGF2":     (0.48755108, 0.39875031, 2.3120353, 0.04338408, 0.09461442, 23.793604, 1.37774, 106.22),
}

# Plastics (single-term Sellmeier fits, C in um^2; approximate, grade dependent)
_PLASTIC = {
    "PMMA": (1.1819, 0.011313, None, None),
    "POLYCARB": (1.4182, 0.021304, None, None),
}


def builtin_catalogs():
    schott = GlassCatalog("SCHOTT", [
        Glass(n, 2, (v[0], v[3], v[1], v[4], v[2], v[5]), catalog="SCHOTT", nd_catalog=v[6], vd_catalog=v[7], wavelength_range=(0.31, 2.5),
              extra={"status": "inquiry" if n in SCHOTT_INQUIRY else "preferred"})
        for n, v in _SCHOTT.items()
    ] + [
        Glass(n, 2, (v[0], v[3], v[1], v[4], v[2], v[5]), catalog="SCHOTT", nd_catalog=v[6], vd_catalog=v[7], wavelength_range=v[8:10],
              extra={"status": "obsolete"})
        for n, v in _SCHOTT_LEGACY.items()
    ] + [
        Glass(n, 1, v[:6], catalog="SCHOTT", nd_catalog=v[6], vd_catalog=v[7], wavelength_range=v[8:10],
              extra={"status": "obsolete"})
        for n, v in _SCHOTT_VISIBLE_FIT.items()
    ])
    misc = GlassCatalog("MISC", [
        Glass(n, 2, (v[0], v[3] ** 2, v[1], v[4] ** 2, v[2], v[5] ** 2), catalog="MISC",
              nd_catalog=v[6], vd_catalog=v[7], wavelength_range=(0.2, 5.0))
        for n, v in _MISC.items()
    ])
    for n, v in _PLASTIC.items():
        misc.add(Glass(n, 2, (v[0], v[1], 0, 0, 0, 0), catalog="MISC",
                       nd_catalog=v[2], vd_catalog=v[3], wavelength_range=(0.4, 1.1)))
    return [schott, misc]
