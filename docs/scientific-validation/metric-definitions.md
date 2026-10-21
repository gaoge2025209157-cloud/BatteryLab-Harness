# Metric definitions and literature basis

Status: definitions adopted for generic calculation; scientific release remains subject to the review gate.

## Operational definitions

For one complete reconstructed charge/discharge pair:

- capacity is `Q = integral(|I| dt) / 3600` in mAh when current is in mA and time is in seconds;
- specific capacity is `Q / m` in mAh/g, where the denominator material and mass must be declared;
- coulombic efficiency is `Q_discharge / Q_charge` for the discharge immediately following its paired charge;
- capacity retention is `Q_discharge,current / Q_discharge,reference`; this project uses the first complete paired discharge as the reference and always records that choice;
- energy is `integral(V |I| dt) / 3600` in mWh;
- capacity-weighted mean voltage is `integral(V |I| dt) / integral(|I| dt)`.

For a three-column time--specific-capacity--voltage export, the source-reported mAh/g values are used directly. The missing current and unrounded time prohibit independent capacity or energy integration. The material represented by `g` remains unaudited until source metadata identifies the denominator.

## Literature support

1. Schulze and Neale define lithium-ion-battery coulombic efficiency as discharge capacity divided by the antecedent charge capacity. This supports the pairing and ratio above. DOI: [10.1021/acsenergylett.1c00173](https://doi.org/10.1021/acsenergylett.1c00173), HTML full text, opening section under the article title.
2. Chen et al. describe specific capacity as charge stored per unit mass of electroactive material and emphasize that performance metrics require declared test conditions. This supports explicit mass-basis and voltage-window provenance. DOI: [10.1038/s41467-018-07599-8](https://doi.org/10.1038/s41467-018-07599-8), HTML full text, sections “All performance metrics matter” and “Specific capacity,” Figure 2.
3. Xiao et al. explain that the meaning of coulombic efficiency depends on battery configuration. This supports recording half-cell/full-cell context and prevents a CE value from being treated as a mechanism by itself. DOI: [10.1038/s41560-020-0648-z](https://doi.org/10.1038/s41560-020-0648-z), abstract-level context only.
4. Liu et al. show why “per gram” requires an explicit denominator and why electrode- and cell-level figures cannot be mixed. DOI: [10.1038/s43246-022-00251-5](https://doi.org/10.1038/s43246-022-00251-5), HTML full text, discussion around Figure 3.

These sources support definitions and reporting boundaries only. They are not treated as directly comparable performance evidence for the current data because rate, temperature, voltage window, mass denominator, and source-cycle mapping are incomplete.
