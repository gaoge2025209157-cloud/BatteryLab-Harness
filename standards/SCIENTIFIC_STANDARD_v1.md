# Scientific Standard v1

Status: project validation draft. This document defines the machine-checkable policy for Work package A. It is not a claim that any individual experiment has passed the release gate.

## 1. Scope and evidence boundary

The first supported workflow is galvanostatic charge/discharge data from a battery tester. The project must distinguish:

- raw device export;
- independently recomputed metrics;
- manually checked values;
- literature evidence;
- model-generated interpretation.

A result may be numerically valid while its scientific interpretation remains blocked. No mechanism, superiority, generality, or direct literature comparison may be inferred from a single unverified result.

## 2. Required experiment context

Before a scientific report can be released, the following must be explicitly recorded or marked unavailable:

- battery system and cell type: half-cell, full-cell, symmetric cell, or other;
- active material and counter electrode/other electrode;
- current or C-rate and its reference mass;
- temperature and voltage window;
- normalization basis: active material, sulfur, composite, electrode, area, or other;
- source file identifier and immutable hash kept outside the public repository when it is private.

For an S/C cathode against Li metal, the context must say `half-cell` and identify Li as the counter electrode. It must not be labelled as a full cell.

## 3. Units and sign conventions

The canonical internal units are:

| Quantity | Canonical unit | Policy |
|---|---|---|
| time | s | strictly increasing in four-column data |
| current | mA | A, mA and uA require explicit conversion metadata |
| voltage | V | mV requires explicit conversion metadata |
| charge/discharge capacity | mAh | trapezoidal integration only when current and time are present |
| specific capacity | mAh g-1 | only when the normalization mass is known and positive |
| energy | mWh | integrate V times absolute current by direction |
| efficiency/retention | fraction and displayed percent | keep the unrounded fraction internally |

The default convention is positive current = charge and negative current = discharge. A LAND export with the opposite convention must carry an explicit sign configuration; the adapter must record the applied reversal.

A current sign crossing is split at zero. A constant-voltage segment is not discarded: its current is integrated using the same direction rule. Zero-current dwell contributes no capacity or energy, but its presence may be retained as provenance.

## 4. Cycle and capacity-reset policy

A cycle is a device-defined or explicitly reconstructed experimental unit. The analyzer must preserve the source cycle number where available and must not silently renumber it.

For three-column time--specific-capacity--voltage exports, a capacity reset is a segmentation signal, not proof of a physical step boundary. The report must label reconstructed segments and must not claim independent current integration or energy calculation.

For deterministic draft calculation on a three-column export, the default reconstruction convention is to retain an initial discharge as an unpaired segment and start reconstructed cycle 1 at the following charge/discharge pair (candidate B). This convention matches the restricted-mode implementation and prevents the initial discharge from being silently paired with a later charge. It is a calculation convention, not proof of the instrument's source-cycle mapping.

The instrument-defined mapping must still be resolved from the step program, cycle field, cutoff conditions, and capacity-reset behavior. Until that source evidence is available:

- show the unpaired source segment and label all calculated cycle numbers as reconstructed;
- do not publish the reconstruction as an instrument-defined cycle map or golden answer;
- do not assign a definitive first-cycle coulombic efficiency;
- do not silently shift all later cycle numbers.

Capacity retention uses the first complete paired discharge cycle only after that reference has been confirmed. An incomplete final cycle remains visible but is excluded from efficiency and retention claims unless the protocol explicitly declares it complete.

## 5. Quality and boundary cases

| Case | Expected handling | Release effect |
|---|---|---|
| missing required column | stop with the missing name | blocking |
| non-finite value | stop | blocking |
| actual time reversal or duplicate time in four-column data | stop before integration | blocking |
| repeated rounded time in three-column export | retain raw point; warn that integration is unavailable | warning |
| missing/zero/negative normalization mass | retain raw capacity; omit specific capacity, or block if required by the requested claim | warning/blocking |
| reversed current convention | require explicit adapter setting and record it | warning until reviewed |
| constant-voltage segment | integrate when current/time exist | no automatic warning |
| incomplete charge or discharge | retain segment; no paired CE/retention | warning |
| negative voltage | report value and request context review | warning, never automatic failure |
| capacity reset | mark reconstructed boundary and preserve source values | warning until validated |
| cycle number jump | preserve source values and report the jump | warning; blocking if pairing becomes ambiguous |
| NaN or Inf | stop | blocking |
| spreadsheet or undocumented binary input | require CSV/TXT export; do not guess | blocking |

## 6. Metric definitions

For a direction-specific interval with current `I` in mA and time `t` in s:

- capacity: `Q = integral(I dt) / 3600`, using absolute current within each direction;
- energy: `E = integral(V |I| dt) / 3600`, reported in mWh;
- coulombic efficiency: `Q_discharge / Q_charge` for a complete paired cycle;
- specific capacity: `Q / m`, where `m` is the declared active mass in g;
- capacity retention: `Q_discharge,current / Q_discharge,reference`;
- capacity-weighted mean voltage: `integral(V |I| dt) / integral(|I| dt)`;
- voltage gap: mean charge voltage minus mean discharge voltage.

A fixed voltage-bin maximum may be described as `capacity-concentrated voltage window`. The stronger term `main plateau` requires a separately approved capacity-fraction threshold and should not be used merely because a bin is the largest.

The literature basis, operational reference-cycle rule, and limits of these definitions are recorded in `docs/scientific-validation/metric-definitions.md`. The formulas remain project definitions and must not be used to infer a material mechanism.

## 7. Validation tolerances

These are project acceptance tolerances, not universal electrochemical standards. They separate numerical reproducibility from agreement with rounded device displays.

### 7.1 Same standardized points, independent implementation

- capacity or energy: `max(1e-9 in the reported unit, 1e-6 * abs(reference))`;
- efficiency or retention: `1e-6` in fraction units;
- voltage: `1e-6 V`;
- segment boundary: same source row, unless the instrument export documents an equivalent boundary.

The basis is floating-point/trapezoidal recomputation on the same unrounded standardized points.

### 7.2 Device display or separately rounded export

Use only as a provisional cross-tool check:

- capacity, specific capacity, or energy: `max(one least-significant displayed digit in the reported unit, 0.1% of reference)`;
- efficiency or retention: `0.1 percentage point`;
- voltage: `max(one least-significant displayed digit, 1 mV)`.

The least-significant digit must be recorded for each compared source. For example,
an export rounded to `0.1 mAh g-1` uses `0.1 mAh g-1`, not the absolute-capacity
unit `mAh`. The basis is displayed precision and export rounding, not a claim of
instrument accuracy. J and C must confirm these tolerances before the scientific
release gate can open.

## 8. Literature evidence levels

Every usable citation requires a DOI that has been independently verified. Evidence is classified as:

1. `abstract`: title/abstract metadata; suitable for discovery and cautious screening only;
2. `html_fulltext`: body text available with section and paragraph/figure/table location;
3. `local_pdf`: authorized local full text with DOI and page/section/figure/table location;
4. `unavailable`: no usable body evidence; never treated as a verified body fact.

Abstract evidence must never be labelled as a正文/full-text fact. Body-level facts require a location. If all comparison conditions are not explicit and aligned, the record is background/context-only rather than directly comparable.

## 9. Scientific reasoning policy

Each candidate explanation must record:

- the observation it attempts to explain;
- supporting evidence;
- contrary evidence or missing evidence;
- the smallest experiment that distinguishes it from alternatives;
- expected observations if the candidate is supported and if it is falsified.

A candidate without a falsifiable experiment is incomplete and cannot support a mechanistic conclusion.

## 10. Scientific release gate

The gate remains closed until all of the following are true:

- private real-data Blue/Manual/Harness comparison has been reviewed without committing the data;
- metric definitions and provisional cross-tool tolerances are confirmed by both J and C;
- all cited evidence has a verified DOI;
- every body-level fact has a section/page/figure/table/paragraph location;
- unresolved cycle mapping, negative voltage, normalization, and incomplete-cycle issues are recorded;
- every hypothesis candidate has a minimum discriminating experiment;
- the required reviewer confirmations for J and C are present.

The software may generate a draft report while the gate is closed, but it must label it as draft/blocked and must not enable a scientific release claim.
