"""Shared fixtures for the test suite."""

from __future__ import annotations

# A trimmed but structurally faithful coastal waters forecast product, based on
# https://tgftp.nws.noaa.gov/data/forecasts/marine/coastal/an/anz230.txt
ANZ230_PRODUCT = """Expires:202609260300;;034305
FZUS51 KBOX 251404
CWFBOX

Coastal Waters Forecast for Massachusetts and Rhode Island
National Weather Service Boston/Norton MA
1003 AM EDT Fri Sep 25 2026

Coastal waters from the Merrimack River MA to Watch Hill RI out
to 60 NM


ANZ230-260300-
Boston Harbor-
1003 AM EDT Fri Sep 25 2026

...STORM WARNING IN EFFECT FROM 2 PM EDT THIS AFTERNOON THROUGH
SATURDAY EVENING...

.THIS AFTERNOON...NE winds around 20 kt with gusts up to 30 kt.
Waves 2 to 3 ft. A chance of rain.
.TONIGHT...NE winds 20 to 25 kt with gusts up to 40 kt. Waves
2 to 3 ft, except 4 to 6 ft at the outer harbor entrance. A
chance of rain. Patchy fog after midnight.
.SAT...NE winds 20 to 25 kt, increasing to 25 to 30 kt in the
afternoon. Gusts up to 55 kt.
.SAT NIGHT...NE winds 25 to 30 kt with gusts up to 55 kt.
.SUN AND SUN NIGHT...NE winds 25 to 30 kt with gusts up to 45 kt.
.MON...NE winds 20 to 25 kt. Waves 2 to 3 ft.

Seas are reported as significant wave height, which is the
average of the highest third of the waves.

$$
"""

# Evening product: THIS AFTERNOON is absent, TONIGHT leads the sequence.
EVENING_PRODUCT = """Expires:202609260100;;000000
FZUS51 KBOX 252015
CWFBOX

Coastal Waters Forecast for Massachusetts and Rhode Island
National Weather Service Boston/Norton MA
803 PM EDT Fri Sep 25 2026

Coastal waters from the Merrimack River MA to Watch Hill RI out
to 60 NM


ANZ230-260100-
Boston Harbor-
803 PM EDT Fri Sep 25 2026

...HIGH WIND WARNING IN EFFECT...

.TONIGHT...W winds 30 to 40 kt with gusts up to 50 kt.
.SAT...W winds 25 to 35 kt with gusts up to 45 kt.
.SAT NIGHT...W winds 20 to 30 kt.
.SUN...NW winds 15 to 20 kt.

$$
"""

# Grouped product, as issued for the western Gulf.
GMZ130_PRODUCT = """Expires:202609252030;;019782
FZUS54 KBRO 250709
CWFBRO

Coastal Waters Forecast for the Lower Texas Coast
National Weather Service Brownsville TX
209 AM CDT Fri Sep 25 2026

Lower Texas coastal waters from Baffin Bay to the mouth of the
Rio Grande out 60 NM.

Seas are provided as a range of the average height of the highest
1/3 of the waves.


GMZ130-132-135-252030-
Laguna Madre from the Port of Brownsville to the Arroyo Colorado-
Laguna Madre from the Arroyo Colorado To 5 NM north of Port
Mansfield TX-
Laguna Madre from 5 nm north of Port Mansfield to Baffin Bay TX-
209 AM CDT Fri Sep 25 2026

.TODAY...East winds 5 to 10 knots, increasing to 10 to 15 knots
this afternoon.
.TONIGHT...East winds 10 to 15 knots, diminishing to 5 to 10
knots after midnight.
.SATURDAY...East winds 5 to 10 knots.
.SATURDAY NIGHT...East winds 5 to 10 knots, becoming southeast
after midnight.
.SUNDAY...Southeast winds around 5 knots.

$$
"""
