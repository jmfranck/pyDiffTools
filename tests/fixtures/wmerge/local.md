## Kinetics of Cold-Shedding

![Another way of presenting the same
spectral-feedback-guided VT data
illustrated in ?????
<JFcom>
  reference appropriate figure
</JFcom>
(5&nbsp;mM TEMPO-SO~4~ inside $w_0=20$ RMs
dispersed in isooctane):
**(a)** Waterfall view of the ESR spectra,
with the same intensity scaling.
**(b)** ESR spectral intensity as a function
of time,
and
**(c)** correlation time $\tau_c$ as a
function of time (blue, left y-axis) together
with the corresponding temperature as a
function of time (orange, right y-axis).
The
time axes of panels (b) and (c) are
aligned.](Figures/Timeseries_combined.png){#fig:IsooctaneKinetics a=fig:KineticsWaterfall b=fig:KineticsSpectra c=fig:KineticsTauTemperature}

The slow timescale of cold-shedding poses a
problem for ESR:
How can an experiment observe shedding
while also exploring the full
temperature range from rt down to no-man's
land?
Simply incrementing temperatures on a slow
timescale is not feasible, as such
experiments could take multiple days,
and cannot be run unsupervised.
For example, sampling temperatures from 300&nbsp;K
down to 230&nbsp;K and then reheating to 295&nbsp;K in 1&nbsp;K increments,
with approximately 2&nbsp;min of acquisition at each temperature,
already requires roughly 4.5 h of measurement time,
even assuming the 2&nbsp;min includes time for the VT controller to stabilize
the temperature.
Including the additional wait periods needed to
observe slow spectral evolution associated with shedding
would be impractical,
because the transition temperatures are not
known *a priori*.

The spectral-feedback-guided VT
procedure
(outlined in @sec:ESRexperimental)
overcomes this challenge.
Specifically,
ESR spectra change in response
to transitions like cold-shedding.
Thus, the spectroscopist continuously
(manually) ramps the temperature,
while also looking for subtle changes in the
spectrum over the timescale of minutes.
When the spectrum changes subtly over the
course of minutes,
the spectroscopist pauses the temperature
ramp to allow the lagging kinetics
to catch up.
Once the ESR spectrum stabilizes
(bearing evidence of completion),
temperature ramping can resume.
<!-- This was closer, and I edited/reworded to try
to get it to what we need-->
Furthermore, once an initial run identifies a
transition temperature in this way,
subsequent runs can pause at earlier
temperatures, waiting for longer periods of time to see if a transition occurs.
(This procedure is analogous to a
titration using a color indicator:
preliminary runs are used to locate the
approximate transition region, after which
subsequent runs take time to focus on that region with finer control.)
Such a spectral-feedback-guided VT experiment
can record complete shedding while also
monitoring molecular dynamics over a range
spanning from above room temperature down
to "no-man’s land."
<!--
  RS: I wrote it here instead of writing in SI--
  "During initial experiments, the temperature was"
  JF: no -- I asked that you not do this for
  a good reason.
-->

@Fig:IsooctaneKinetics reveals that the onset
of water shedding at 260&nbsp;K proceeds
following first-order
(or approximately first-order) kinetics,
over a timescale of 42.2&nbsp;min.
Specifically,
the rate of conversion of RMs to RMs with a
slower $\tau_c$ appears proportional to the
number of RMs that have already converted
(likely because this is proportional to the
number of active ice nuclei in the sample).
Such a rate equation
yields the black exponential curve shown in
@fig:KineticsTauTemperature,
which indicates a rate constant of
$1/42.2\;\text{min}=1.42\;\text{hr}^{-1}$.
<JFcom>
  this next paragraph will likely move after
  @fig:fusionFission
  → leaving for now to avoid conflicts
</JFcom>
The spectral-feedback-guided VT experiment
of @fig:IsooctaneKinetics
also places upper and lower bounds on the
shedding temperature.
Specifically,
a 20&nbsp;min pause at 271&nbsp;K
(orange line in @fig:KineticsTauTemperature)
shows no
significant change in the ESR spectrum
(blue markers in @fig:KineticsTauTemperature),
indicating no nucleation and shedding at that temperature.
The abrupt change in the spectrum
at 260&nbsp;K provides a lower limit
for the cold-shedding transition,
while any cold-shedding $\ge 271\;\text{K}$
takes longer than 20&nbsp;min to yield
any noticeable effect.
<!-- JF to here-->
Indeed,
when looking for shedding (or any nucleation)
at a particular temperature,
holding at that temperature
for a longer time
increases the likelihood
that a stable nucleus will form.
<!-- deleted "passcode" that matches to the next
line-->
<!-- A bunch of back and forth commentary
leads to the following additions:
JF will take the time to re-read in detail,
even though this is possibly a
delay/distraction -->
This timescale-dependence is important to
keep in mind when interpreting
prior observations of cold-shedding
that report wider ranges,
with required temperatures sometimes
quoted as low as 243&nbsp;K
[@VanHorn2009RevMicEnc; @Bai2019ProCriNuc; @Simorellis2006DynLowTem].
<!-- highest freezing by Flynn mentioned at SW! re fre ov t ra-->

### no water reincorp. here; light vs. dark = sampling density

After cold-shedding,
the RM aggregates can sometimes reincorporate
water molecules
that were previously expelled from the core.
The darker regions of the curves in
@fig:IsoTSO4TempCycle correspond to
periods where the temperature changes more slowly,
resulting in more data points being acquired
over a narrower temperature interval.
Notably, the darker region of the re-warming curve near 273&nbsp;K
in @fig:IsoTSO4TempCycle indicates that
despite being held at slightly above
273&nbsp;K for $\sim 20\;\text{min}$
there is no evidence of water molecules
being reincorporated into the RM.
However, such an effect is occasionally
observed (*e.g.* @fig:TempoIsoTooWetData),
and when present,
it increases the final $w_0$ after shedding.

### nucleation sensitive to prep/vibration; better control → slower shedding [Red.? kinetic limit]

<JFcom>
  this paragraph is now ready to be moved to
  the top of this subsection (before "the slow
  timescale of cold-shedding poses a
  problem..."
  After doing that, we need to carefully read
  the subsection to see that it makes sense.
</JFcom>
Cold-shedding is a kinetically limited
process.
<!-- RS: moved from RM prep. -- originally "Note that,
  ice nucleation events are highly -->
Because of this, the temperature at which
cold-shedding (or nucleation in general)
becomes evident depends
as much on timescale as on other
(thermodynamically relevant) factors.
<!-- after pulling some things up, I moved this
whole thing down, since it's more about the
general process -->
<!--RS says that
highest shedding, in
@Simorellis2006DynLowTem,
is observed at 263 K.
(She also references Bai2019ProCriNuc, which
doesn't seem relevant in this context.-->
<!-- what was said here was redundant with
SW! in fre wat mu hi te -->
<!-- removed reference to Bai here, which was out
of place-->
<!-- following sentence moved up from below (was "SW! su dif a na ex" before as well) -->
Practically, to observe nucleation,
one must ask whether or not it occurs within
a given finite timescale;
thus the apparent nucleation temperature
depends strongly on experimental parameters
that control the kinetics.
Notably, difficult to control experimental
parameters,
such as initial preparation and equilibration
of the RM,
sample tube size,
and mechanical vibrations,
likely influence the
nucleation kinetics and, thus,
the apparent cold-shedding temperature.
Furthermore,
carefully controlling conditions
to ensure the reliability and reproducibility
of the measurements tends to deter nucleation.
For example,
stabilization of the ESR sample tube holder to
prevent vibrations almost entirely suppresses
an almost immediate (10 seconds) shedding
that sometimes occurs when only flexible
teflon holds the sample capillary
(@fig:TEMPOIso_w20_OldData).
In fact, more controlled
(and therefore reproducible) experiments,
control vibrations and sample
impurities that can lead to inhomogeneous
nucleation,
and ultimately
lead to water shedding with slower kinetics.

### kinetic limitation: apparent shedding T depends on hold time [Red.? kinetic limit]

Of course,
ice nucleation is strongly influenced by the
degree of confinement --
an observation that
arises from the fact that
the number of available water molecules is reduced,
making it increasingly difficult for an
embryo to reach the critical radius required to form
a stable ice nucleus
[@Quist1988WatDynAgg; @Liu2007DirMeaCri; @Bai2019ProCriNuc].
<!-- I saw two different themes here, and grouped
into two paragraphs with appropriate topic
sentences-->
Such thermodynamic limitations
differ from considerations of the kinetics of
nucleus formation -- although the latter can
affect observations of the former.

### nucleation needs fusion-fission to grow embryos → rare, hence slow

Successful nucleation (required for
cold-shedding) within RMs
requires fusion–fission events between
aggregates,
which allow ice embryos
(*i.e.* transient, pre-nucleation structures)
to acquire additional
water molecules.
Without such
exchange, embryos remain subcritical and
revert to the liquid state
(@fig:fusionFission).
Ice embryos
form spontaneously only rarely,
and the fusion/fission events required to supply
additional water molecules for embryo growth
inside the RM also occur only infrequently.
Consequently, stable ice nucleus formation
occurs exceedingly rarely,
leading to the 42.2&nbsp;min timesccale in @fig:IsooctaneKinetics.
(Of course,
once a stable ice nucleus forms,
collision with additional RMs likely rapidly
increases the size of the resulting ice
crystal and the accelerates removal of water
from the RM phase.)

