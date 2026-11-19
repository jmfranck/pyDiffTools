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
temperature range from room temperature down to no-man's
land?
Gradually increasing the temperature over an
extended period is impractical, as such
experiments could take multiple days
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
The spectroscopist continuously (manually) ramps the temperature,
while monitoring for subtle changes in the
ESR spectrum over the timescale of minutes.
When the spectrum changes subtly over the
course of minutes,
the spectroscopist pauses the temperature
ramp to allow the lagging kinetics to approach equilibrium.
Once the ESR spectrum stabilizes,
indicating that the process has reached
completion, temperature ramping resumes.
<!-- This was closer, and I edited/reworded to try
to get it to what we need-->
After an initial run identifies a
transition temperature in this way,
subsequent runs can pause at earlier
temperatures to test whether a transition occurs there.
(This procedure is analogous to a
titration using a color indicator:
preliminary runs are used to locate the
approximate transition region, after which
subsequent runs focus on that region with finer control.)
Such a "spectral-feedback-guided" variable
temperature experiment
can record complete cold-shedding while also
monitoring molecular dynamics over a range
spanning from above room temperature down
to "no-man’s land."
<!--
  RS: I wrote it here instead of writing in SI--
  "During initial experiments, the temperature was"
  JF: no -- I asked that you not do this for
  a good reason.
3/11 RS: I think this is solved or do I need
to anything here?
-->

@Fig:IsooctaneKinetics reveals that the onset
of water shedding at 260&nbsp;K proceeds
following first-order (or approximately first-order) kinetics,
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
also places upper and lower bounds on the shedding temperature.
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

<RScom>
  11/4 RS: this para should come later with
  "RMs reincorporate some shed water".
</RScom>
After cold-shedding,
the RM aggregates can sometimes reincorporate
water molecules
that were previously expelled from the core.
<RScom>
  the following sentence should move to
  with figure [@fig:TempCycles (a)].
</RScom>The darker regions of the curves in
[@fig:TempCycles (a)] correspond to
periods where the temperature changes more slowly,
resulting in more data points being acquired
over a narrower temperature interval.
<RScom>
  the following sentence should move to
  reheating section:
  "during reheating, cumulant shows evidence of ice redissol".
</RScom>Notably, the darker region of the re-warming
curve near 273&nbsp;K in [@fig:TempCycles
(a)] indicates that despite being held at slightly above
273&nbsp;K for $\sim 20\;\text{min}$
there is no evidence of water molecules
being reincorporated into the RM.
<RScom>
  To confirm, we are saying
  both dataset shows ice reincorporation, right?
</RScom>
However, such an effect is occasionally
observed (*e.g.* @fig:TempoIsoTooWetData),
and when present,
it increases the final $w_0$ after shedding.

### nucleation sensitive to prep/vibration; better control → slower shedding [Red.? kinetic limit]

Ice nucleation, and therefore the kinetics of
cold-shedding, is highly sensitive to experimental conditions, such as RM preparation and equilibration procedures,
and mechanical vibrations during measurement, *etc.*
Furthermore,
carefully controlling conditions
to ensure the reliability and reproducibility
of the measurements can suppress nucleation.
For example,
stabilizing the ESR sample tube holder with a quartz support
(@fig:Sample_holder_scheme_quartz)
reduces vibrations during measurement and
supresses the almost immediate shedding
(within 10 seconds) sometimes observed
(@fig:TEMPOIso_w20_OldData, orange) when the sample capillary is supported only
by a flexible Teflon tube
(@fig:Sample_holder_scheme_teflon).
Ultimately, better-controlled
(and therefore more reproducible) experiments,
which minimizes vibrations and sample
impurities that promote heterogeneous
nucleation,
can lead to slower kinetics for water shedding.

### kinetic limitation: apparent shedding T depends on hold time [Red.? kinetic limit]

Because of this kinetic limitation,
the temperature at which
cold-shedding (or nucleation in general)
becomes observable depends as much on the
experimental timescale as on other
thermodynamic factors.
Of course,
ice nucleation is strongly influenced by the degree of confinement,
which limits the number of available water molecules and hinders the growth of an
embryo to the critical radius required to form
a stable ice nucleus
[@Quist1988WatDynAgg; @Liu2007DirMeaCri; @Bai2019ProCriNuc].
<!-- I saw two different themes here, and grouped
into two paragraphs with appropriate topic
sentences-->
Such thermodynamic limitations
are distinct from the kinetics of
nucleus formation, although the latter can
affect observations of the former.
Indeed,
when monitoring cold-shedding (or any nucleation)
at a particular temperature,
holding the sample longer
increases the likelihood
that a stable nucleus will form.
<!-- deleted "passcode" that matches to the next
line-->
<!-- A bunch of back and forth commentary
leads to the following additions:
JF will take the time to re-read in detail,
even though this is possibly a
delay/distraction --> Observation time should
therefore be considered when comparing
reported cold-shedding temperatures,
including values as low as 243&nbsp;K
[@VanHorn2009RevMicEnc; @Simorellis2006DynLowTem].
<!-- 11/4 RS: @Bai2019ProCriNuc reported
lowest at -27.8 C (245.2 K) --> <!--
highest freezing by Flynn mentioned at SW! re fre ov t ra-->

### kinetics alter apparent shedding T (not just thermodynamic) [Red.? kinetic limit]

<RScom>
  *Delete this para*. It's re-state the above two para.
  No new information added in this para.
</RScom>

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
SW: in fre wat mu hi te -->
<!-- removed reference to Bai here, which was out
of place-->
<!-- following sentence moved up from below (was "SW: su dif a na ex" before as well) -->
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

Fusion–fission events between RM aggregates
can contribute to the slow kinetics of
cold-shedding by allowing ice embryos
(*i.e.* transient, pre-nucleation structures)
to acquire additional water molecules
(@fig:fusionFission).
Without such
exchange, embryos remain subcritical and
revert to the liquid state
(@fig:fusionFission).
Ice embryos
form spontaneously only rarely,
and the fusion/fission events required to supply
additional water molecules for embryo growth are also infrequent.
Consequently, stable ice nuclei formation
occurs exceedingly rarely,
consistent with the 42.2&nbsp;min fitted time
constant observed in @fig:IsooctaneKinetics.
(Of course,
once a stable ice nucleus forms,
collision with additional RMs likely rapidly
increases the size of the resulting ice
crystal and the accelerates removal of water
from the RM phase.)

