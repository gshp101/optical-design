"""Optimisation and tolerancing for lensforge.

Typical use::

    import lensforge as lf
    from lensforge import optimize as opt

    lens = lf.samples.singlet()
    opt.set_variable(lens, 1, "curvature")
    opt.set_variable(lens, 2, "curvature")
    opt.set_solve(lens, opt.MarginalRayHeight(lens.image_index - 1))   # image at paraxial focus
    mf = opt.default_merit(lens, "spot")                               # RMS spot, centroid
    mf.add("EFFL", 100.0, -1)                                          # hard constraint
    res = opt.optimize(lens, mf)
    print(res, mf.table(lens))

Contents: variables and solves (:mod:`.variables`, :mod:`.solves`), operands
and the merit function editor (:mod:`.operands`, :mod:`.merit`), damped least
squares (:mod:`.dls`), global search and hammer (:mod:`.global_opt`), glass
substitution (:mod:`.glass`) and tolerancing (:mod:`.tolerance`).
"""

from .variables import (MCVariable, Variable, VariableSet, clear_variables, get_param, is_mc_variable,
                        remove_mc_variable, remove_variable, set_mc_variable, set_param, set_variable,
                        to_model_glass, variable_from_dict, variables, vary_curvatures, vary_thicknesses)
from .solves import (ChiefRayAngle, ChiefRayHeight, Concentric, EdgeThickness, FNumber, MarginalRayAngle,
                     MarginalRayHeight, Pickup, Position, Solve, apply_solves, remove_solve, set_solve, solves,
                     solve_from_dict)
from .operands import OPERAND_INFO, OPERANDS, Block, EvalContext, gaussian_quadrature, is_symmetric
from .merit import MeritFunction, Operand, default_merit, operand_help
from .dls import OptimizationResult, merit_value, optimize
from .global_opt import GlobalResult, global_search, hammer
from .glass import glass_substitution, nearest_glasses, snap_to_catalog
from .tolerance import (MonteCarloResult, Tolerance, default_tolerances, inverse_sensitivity, monte_carlo,
                        perturbed_system, sensitivity_analysis)
