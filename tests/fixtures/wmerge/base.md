## Kinetics of Cold-Shedding

![Another way of presenting the same
feedback-guided variable temperature data
illustrated in ?????
<JFcom>
  reference appropriate figure
</JFcom>
(5&nbsp;mM TEMPO-SO~4~ inside $w_0=20$ RMs
dispersed in isooctane).
The top panel shows the ESR spectral
<JFcom>
  CODEX: here, rather than "top panel shows ESR
  spectral"
  say "**(a)** ESR spectral"
</JFcom>
intensity as a function of time.
The bottom
panel shows the correlation time $\tau_c$ as a
function of time (blue, left y-axis) together
with the corresponding temperature as a
function of time (orange, right y-axis).
The
time axes of the two panels are
aligned.](Figures/Timeseries_spec.png){#fig:IsooctaneKinetics}

<JFcom>
  CODEX:
  since the intensity units are arbitrary in
  the top plot, rescale them to run from -100
  to +100 Also, use the same colors for the
  bottom plot, but adjust the marker styles so
  that they are more consistent (in terms of
  alpha, size, and "o" vs.
  ".", etc, and edge
  color) e.g. with the green markers in figure
  6a.
  Also, add subfigure labels consistent with
  figure 10.
  Try to change references in the text to
  subfigure references where possible.
  While you are at it, adjust the style of the
  subfigure labels in figure 6 and 10, so that
  all are consistent.
  Make bold, and with a
  size of about 0.25 where 0 is figure 10 and 1
  is figure 6.
  Also, make a nice serif font
  (so it's more consistent with the captions)
  and make the labels in the captions bold.
</JFcom>

<JFcom>
  CODEX:
  pyspecdata has a nice waterfall
  implementation.
  Inspect graphically, and choose a nice angle,
  and show this here as an alternative to 11a
  (include in the same code that generates
  11, but output to a different PNG)
</JFcom>

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
with approximately 2 min of acquisition at each temperature,
already requires roughly 4.5 h of measurement time.
Including the additional wait periods needed to
observe slow spectral evolution associated with shedding
would be impractical,
because the transition temperatures are not
known *a priori*.
The spectral-feedback-guided VT
procedure
(outlined in @sec:?????)
<JFcom>
  CODEX: subsitute the reference to the methods
  section, and also make sure we use this same
  phrasing "spectral-feedback-guided VT"
  throughout, with quotes only where it's
  first explained in the methods section.
  (VT acronym to be expanded by acronyms
  package, so never expand and never give
  long form here)
</JFcom>
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
ramp to allow the lagging kinetics a chance
to catch up.
Once the ESR spectrum stabilizes
(bearing evidence of completion),
temperature ramping can resume.
<!-- This was closer, and I edited/reworded to try
to get it to what we need-->
Furthermore, once an initial run identifies a
transition temperature in this way,
subsequent runs can pause at earlier
temperatures, to see if a transition occurs.
(This procedure is analogous to a
titration using a color indicator:
preliminary runs are used to locate the
approximate transition region, after which
subsequent runs focus on that region with finer control.)
Such a "spectral-feedback-guided" variable
temperature experiment
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
at a timescale of 42.2&nbsp;min.
Specifically,
the rate of conversion of RMs to RMs with a
slower $\tau_c$ appears proportional to the
number of RMs that have already converted
(likely because this is proportional to the
number of active ice nuclei in the sample).
Such a rate equation
yields the black exponential curve shown in
@fig:IsooctaneKinetics,
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
(see orange line in @Fig:IsooctaneKinetics bottom panel)
shows no
significant change in the ESR spectrum
(see blue line in @Fig:IsooctaneKinetics bottom panel),
indicating no nucleation and shedding at that temperature.
The abrupt change in the spectrum
at 260&nbsp;K provides a lower limit
for the cold-shedding transition,
while the 20&nbsp;min pause sets an upper limit
on the transition at 271&nbsp;K.
<JFcom>
  Here, we need to say that we might see
  something even as high as 271 if we were to
  wait longer → but I think that's below and
  just needs to be pulled up
</JFcom>
<!-- JF to here-->

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

<!-- RS: moved from RM prep. -- originally "Note that,
  ice nucleation events are highly -->
Ice nucleation events are
highly sensitive to the experimental parameters
that can lead to changes in the kinetics of
cold shedding.
Such experimental parameters include
the RM equilibration procedure,
vibrations during measurement, *etc.*
Furthermore,
carefully controlling conditions
to ensure the reliability and reproducibility
of the measurements can deter nucleation.
For example,
we note that
stabilizing the ESR sample tube holder to
prevent vibrations results in supression of
an almost immediate (10 seconds) shedding
that can sometimes be seen when only flexible
teflon holds the sample capillary
(@fig:TEMPOIso_w20_OldData).
Ultimately, more controlled
(and therefore reproducible) experiments,
by controlling vibrations and sample
impurities that can lead to inhomogeneous
nucleation,
lead to slower kinetics for water shedding.

### kinetic limitation: apparent shedding T depends on hold time [Red.? kinetic limit]

Because of this kinetic limitation,
the temperature at which
cold-shedding (or nucleation in general)
becomes evident depends
as much on timescale as on other
(thermodynamically relevant) factors.
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

### kinetics alter apparent shedding T (not just thermodynamic) [Red.? kinetic limit]

<!-- after pulling some things up, I moved this
whole thing down, since it's more about the
general process -->
<!--RS says that
highest shedding, in
@Simorellis2006DynLowTem,
is observed at 263 K.
(She also references Bai2019ProCriNuc, which
doesn't seem relevant in this context.-->
It is important to note that
the temperature at which cold-shedding is
observed reflects not only thermodynamic
conditions but also the kinetics of
nucleation.
<!-- what was said here was redundant with
SW! in fre wat mu hi te -->
<!-- removed reference to Bai here, which was out
of place-->
<!-- following sentence moved up from below (was "SW! su dif a na ex" before as well) -->
The successful formation of a
transient ice embryo and its subsequent
conversion into a stable ice
nucleus depends on a combination of kinetic
factors that consequently
governs the apparent nucleation temperature.
Notably, difficult to control experimental
parameters,
such as initial preparation and equilibration
of the RM,
sample tube size,
or mechanical vibrations,
might also influence the
nucleation kinetics,
and the apparent cold-shedding temperature.

### nucleation needs fusion-fission to grow embryos → rare, hence slow

Cold-shedding is a kinetically limited
process.
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

