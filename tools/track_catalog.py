"""Real tracks for the designer's "Real tracks" menu.

Each entry is matched against OpenStreetMap by location and official lap length, so the right configuration is
picked even where several share the same venue (e.g. Daytona's oval vs. its road course).

Fields:
  id, name, config, series, kind ("oval" | "road" | "street"), length (official lap, m), direction ("cw" | "acw"),
  lat, lon (roughly the middle of the venue)
  banking (ovals): turns = one value for every turn, or a list in driving order from the start line;
                   front / back = banking of the start/finish straight and of the other straights (degrees)
  bank_from: id of an oval whose banking applies wherever this layout runs on that oval
  sf_shift: move the start/finish line this many metres along the track from the middle of the front straight
  width: road width (m) if not the default for its kind
  tol: accept OSM loops this far from the official length (default 0.08); scale_to_length: then resize to it
  elevation: "flat" to skip terrain data where it is known to be wrong
Banking figures are published specs (rounded); several tracks have progressive banking, simplified to one value.
"""

DEFAULT_WIDTH = {"oval": 15.0, "road": 13.0, "street": 11.0}
SERIES_PITS = {"IMSA": 50, "NASCAR": 40, "INDYCAR": 28, "F1": 22}


def T(id, name, config, series, kind, length, direction, lat, lon, **opts):
    return dict(id=id, name=name, config=config, series=series, kind=kind, length=length, direction=direction,
                lat=lat, lon=lon, **opts)


def B(turns, front=0.0, back=0.0, nturns=None):
    """nturns: how many separate banked turns the oval has, when `turns` is one value (default 2)."""
    return dict(turns=turns, front=front, back=back, nturns=nturns)


MI = 1609.344

TRACKS = [
    # ---------------------------------------------------------------- NASCAR ovals
    T("daytona_oval", "Daytona International Speedway", "Oval", ["NASCAR"], "oval", 2.5 * MI, "acw", 29.1852, -81.0705,
      banking=B(31, 18, 3)),
    T("talladega", "Talladega Superspeedway", "Oval", ["NASCAR"], "oval", 2.66 * MI, "acw", 33.5662, -86.0700,
      banking=B(33, 16.5, 2), width=14.6, sf_shift=381),
    T("atlanta", "Atlanta Motor Speedway", "Oval", ["NASCAR"], "oval", 1.54 * MI, "acw", 33.3838, -84.3170,
      banking=B(28, 5, 5)),
    T("phoenix", "Phoenix Raceway", "Oval", ["NASCAR"], "oval", 1.022 * MI, "acw", 33.3747, -112.3110,
      banking=B([11, 9], 3, 3)),
    T("las_vegas", "Las Vegas Motor Speedway", "Oval", ["NASCAR"], "oval", 1.5 * MI, "acw", 36.2722, -115.0103,
      banking=B(20, 9, 3)),
    T("homestead", "Homestead-Miami Speedway", "Oval", ["NASCAR"], "oval", 1.5 * MI, "acw", 25.4517, -80.4089,
      banking=B(20, 4, 4)),
    T("martinsville", "Martinsville Speedway", "Oval", ["NASCAR"], "oval", 0.526 * MI, "acw", 36.6342, -79.8516,
      banking=B(12, 0, 0), width=16),
    T("darlington", "Darlington Raceway", "Oval", ["NASCAR"], "oval", 1.366 * MI, "acw", 34.2955, -79.9056,
      banking=B([25, 23], 3, 2)),
    T("bristol", "Bristol Motor Speedway", "Oval", ["NASCAR"], "oval", 0.533 * MI, "acw", 36.5157, -82.2570,
      banking=B(26, 7, 7), width=13),
    T("texas", "Texas Motor Speedway", "Oval", ["NASCAR"], "oval", 1.5 * MI, "acw", 33.0372, -97.2811,
      banking=B([20, 24], 8, 5)),
    T("kansas", "Kansas Speedway", "Oval", ["NASCAR"], "oval", 1.5 * MI, "acw", 39.1155, -94.8311,
      banking=B(18.5, 10, 5)),
    T("charlotte_oval", "Charlotte Motor Speedway", "Oval", ["NASCAR"], "oval", 1.5 * MI, "acw", 35.3523, -80.6830,
      banking=B(24, 5, 5)),
    T("charlotte_roval", "Charlotte Motor Speedway", "ROVAL", ["NASCAR"], "road", 2.28 * MI, "acw", 35.3523, -80.6830,
      bank_from="charlotte_oval"),
    T("nashville_ss", "Nashville Superspeedway", "Oval", ["NASCAR", "INDYCAR"], "oval", 1.333 * MI, "acw", 36.0453, -86.4126,
      banking=B(14, 9, 6)),
    T("michigan", "Michigan International Speedway", "Oval", ["NASCAR"], "oval", 2.0 * MI, "acw", 42.0670, -84.2412,
      banking=B(18, 12, 5)),
    T("pocono", "Pocono Raceway", "Tricky Triangle", ["NASCAR"], "oval", 2.5 * MI, "acw", 41.0553, -75.5114,
      banking=B([14, 8, 6], 0, 0)),
    T("dover", "Dover Motor Speedway", "Oval", ["NASCAR"], "oval", 1.0 * MI, "acw", 39.1899, -75.5302,
      banking=B(24, 9, 9)),
    T("indy_oval", "Indianapolis Motor Speedway", "Oval", ["NASCAR", "INDYCAR"], "oval", 2.5 * MI, "acw", 39.7950, -86.2353,
      banking=B(9.2, 0, 0, nturns=4), width=15),
    T("iowa", "Iowa Speedway", "Oval", ["NASCAR", "INDYCAR"], "oval", 0.875 * MI, "acw", 41.6758, -93.0136,
      banking=B(13, 10, 4)),
    T("richmond", "Richmond Raceway", "Oval", ["NASCAR"], "oval", 0.75 * MI, "acw", 37.5918, -77.4196,
      banking=B(14, 8, 2)),
    T("new_hampshire", "New Hampshire Motor Speedway", "Oval", ["NASCAR"], "oval", 1.058 * MI, "acw", 43.3624, -71.4605,
      banking=B(6, 1, 1)),
    T("gateway", "World Wide Technology Raceway", "Oval", ["NASCAR", "INDYCAR"], "oval", 1.25 * MI, "acw", 38.6511, -90.1356,
      banking=B([11, 9], 3, 3)),
    # OSM's North Wilkesboro trace is 16% short of the official length: accept it and scale it up to size
    T("north_wilkesboro", "North Wilkesboro Speedway", "Oval", ["NASCAR"], "oval", 0.625 * MI, "acw", 36.1430, -81.0710,
      banking=B(14, 3, 3), tol=0.2, scale_to_length=True),
    T("bowman_gray", "Bowman Gray Stadium", "Oval", ["NASCAR"], "oval", 0.25 * MI, "acw", 36.0827, -80.2221,
      banking=B(0, 0, 0), width=12),
    T("milwaukee", "Milwaukee Mile", "Oval", ["INDYCAR"], "oval", 1.015 * MI, "acw", 43.0195, -88.0110,
      banking=B(9.25, 2.5, 2.5)),

    # ---------------------------------------------------------------- road courses
    T("daytona_rc", "Daytona International Speedway", "Road Course (Rolex 24)", ["IMSA"], "road", 3.56 * MI, "acw",
      29.1852, -81.0705, bank_from="daytona_oval"),
    T("indy_rc", "Indianapolis Motor Speedway", "Road Course", ["INDYCAR", "IMSA"], "road", 2.439 * MI, "cw",
      39.7950, -86.2353, bank_from="indy_oval"),
    T("cota", "Circuit of the Americas", "Grand Prix", ["F1", "NASCAR"], "road", 5513, "acw", 30.1328, -97.6411),
    T("sonoma", "Sonoma Raceway", "NASCAR Course", ["NASCAR"], "road", 1.99 * MI, "cw", 38.1611, -122.4547),
    T("watkins_glen_short", "Watkins Glen International", "Short Course", ["NASCAR"], "road", 2.45 * MI, "cw",
      42.3369, -76.9272),
    T("watkins_glen_full", "Watkins Glen International", "Grand Prix (with Boot)", ["IMSA"], "road", 3.4 * MI, "cw",
      42.3369, -76.9272),
    # flat in reality; SRTM over the park's trees and stadium gives ±5 m waves
    T("mexico", "Autodromo Hermanos Rodriguez", "Grand Prix", ["F1", "NASCAR"], "road", 4304, "cw", 19.4042, -99.0907,
      elevation="flat"),
    T("road_america", "Road America", "Full Course", ["INDYCAR", "IMSA"], "road", 4.048 * MI, "cw", 43.7978, -87.9897),
    T("barber", "Barber Motorsports Park", "Full Course", ["INDYCAR"], "road", 2.38 * MI, "cw", 33.5325, -86.6194),
    T("mid_ohio", "Mid-Ohio Sports Car Course", "Full Course", ["INDYCAR", "IMSA"], "road", 2.258 * MI, "cw", 40.6892, -82.6364),
    T("laguna_seca", "WeatherTech Raceway Laguna Seca", "Full Course", ["INDYCAR", "IMSA"], "road", 2.238 * MI, "acw",
      36.5843, -121.7535),
    T("portland", "Portland International Raceway", "Full Course", ["INDYCAR"], "road", 1.964 * MI, "cw", 45.5950, -122.6944),
    T("thermal", "The Thermal Club", "INDYCAR Course", ["INDYCAR"], "road", 3.067 * MI, "cw", 33.6020, -116.1530),
    T("sebring", "Sebring International Raceway", "Full Course", ["IMSA"], "road", 3.74 * MI, "cw", 27.4545, -81.3484),
    T("road_atlanta", "Michelin Raceway Road Atlanta", "Full Course", ["IMSA"], "road", 2.54 * MI, "cw", 34.1462, -83.8139),
    T("vir", "VIRginia International Raceway", "Full Course", ["IMSA"], "road", 3.27 * MI, "cw", 36.5683, -79.2063),
    T("ctmp", "Canadian Tire Motorsport Park", "Grand Prix", ["IMSA"], "road", 2.459 * MI, "cw", 44.0526, -78.6747),
    T("lime_rock", "Lime Rock Park", "Full Course", ["IMSA"], "road", 1.53 * MI, "cw", 41.9286, -73.3828),
    T("bahrain", "Bahrain International Circuit", "Grand Prix", ["F1"], "road", 5412, "cw", 26.0325, 50.5106),
    T("shanghai", "Shanghai International Circuit", "Grand Prix", ["F1"], "road", 5451, "cw", 31.3389, 121.2197),
    T("imola", "Autodromo Enzo e Dino Ferrari (Imola)", "Grand Prix", ["F1"], "road", 4909, "acw", 44.3439, 11.7167),
    T("barcelona", "Circuit de Barcelona-Catalunya", "Grand Prix", ["F1"], "road", 4657, "cw", 41.5700, 2.2611),
    T("red_bull_ring", "Red Bull Ring", "Grand Prix", ["F1"], "road", 4318, "cw", 47.2197, 14.7647),
    T("silverstone", "Silverstone Circuit", "Grand Prix", ["F1"], "road", 5891, "cw", 52.0786, -1.0169),
    T("spa", "Circuit de Spa-Francorchamps", "Grand Prix", ["F1"], "road", 7004, "cw", 50.4372, 5.9714),
    T("hungaroring", "Hungaroring", "Grand Prix", ["F1"], "road", 4381, "cw", 47.5789, 19.2486),
    T("zandvoort", "Circuit Zandvoort", "Grand Prix", ["F1"], "road", 4259, "cw", 52.3888, 4.5409),
    T("monza", "Autodromo Nazionale Monza", "Grand Prix", ["F1"], "road", 5793, "cw", 45.6156, 9.2811),
    T("interlagos", "Autodromo Jose Carlos Pace (Interlagos)", "Grand Prix", ["F1"], "road", 4309, "acw", -23.7036, -46.6997),
    T("lusail", "Lusail International Circuit", "Grand Prix", ["F1"], "road", 5419, "cw", 25.4900, 51.4542),
    T("yas_marina", "Yas Marina Circuit", "Grand Prix", ["F1"], "road", 5281, "acw", 24.4672, 54.6031),

    # ---------------------------------------------------------------- street circuits (walls close to the track)
    T("monaco", "Circuit de Monaco", "Grand Prix", ["F1"], "street", 3337, "cw", 43.7347, 7.4206),
    T("baku", "Baku City Circuit", "Grand Prix", ["F1"], "street", 6003, "acw", 40.3725, 49.8533),
    # SRTM reads Singapore's skyline as a 20 m plateau; the real circuit is nearly flat reclaimed land
    T("singapore", "Marina Bay Street Circuit", "Grand Prix", ["F1"], "street", 4940, "acw", 1.2914, 103.8640,
      elevation="flat"),
    T("jeddah", "Jeddah Corniche Circuit", "Grand Prix", ["F1"], "street", 6174, "acw", 21.6319, 39.1044),
    T("las_vegas_strip", "Las Vegas Strip Circuit", "Grand Prix", ["F1"], "street", 6201, "acw", 36.1147, -115.1728),
    T("miami", "Miami International Autodrome", "Grand Prix", ["F1"], "street", 5412, "acw", 25.9581, -80.2389),
    T("albert_park", "Albert Park Circuit", "Grand Prix", ["F1"], "street", 5278, "cw", -37.8497, 144.9680),
    T("montreal", "Circuit Gilles Villeneuve", "Grand Prix", ["F1"], "street", 4361, "cw", 45.5000, -73.5228, width=13),
    T("long_beach", "Long Beach Street Circuit", "Grand Prix", ["INDYCAR", "IMSA"], "street", 1.968 * MI, "cw",
      33.7649, -118.1926),
    T("st_petersburg", "Streets of St. Petersburg", "Grand Prix", ["INDYCAR"], "street", 1.8 * MI, "cw", 27.7668, -82.6293),
    T("toronto", "Exhibition Place Street Circuit", "Toronto", ["INDYCAR"], "street", 1.786 * MI, "cw", 43.6339, -79.4158),
    T("detroit", "Detroit Street Circuit", "Downtown", ["INDYCAR", "IMSA"], "street", 1.645 * MI, "cw", 42.3290, -83.0410),
    T("chicago", "Chicago Street Course", "Grant Park", ["NASCAR"], "street", 2.2 * MI, "cw", 41.8708, -87.6180),
]
