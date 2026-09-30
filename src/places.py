from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


PLACES = [
    Place("Jinnah International Airport (Terminal Road)", 24.9130, 67.1492),
    Place("Saddar (Empress Market)", 24.8560, 67.0290),
    Place("Clifton Sea View", 24.7979, 67.0369),
    Place("Dolmen Mall Clifton", 24.8010, 67.0335),
    Place("Karachi University (KU Circular Road)", 24.9409, 67.1170),
    Place("Gulshan-e-Iqbal", 24.9200, 67.0950),
    Place("North Nazimabad (Five Star)", 24.9400, 67.0430),
    Place("Korangi Crossing", 24.8330, 67.1200),
    Place("Port Grand", 24.8420, 66.9990),
    Place("Mazar-e-Quaid", 24.8752, 67.0398),
    Place("Frere Hall", 24.8464, 67.0325),
    Place("Do Talwar", 24.8175, 67.0325),
    Place("Zamzama", 24.8190, 67.0400),
    Place("PECHS (Tariq Road)", 24.8734, 67.0630),
    Place("Bahadurabad", 24.8800, 67.0680),
    Place("Nazimabad", 24.9050, 67.0260),
    Place("Liaquatabad", 24.9050, 67.0450),
    Place("NED University", 24.9337, 67.1115),
    Place("Aga Khan University Hospital", 24.8918, 67.0738),
    Place("National Stadium", 24.8925, 67.0845),
    Place("I.I. Chundrigar Road", 24.8477, 67.0080),
    Place("Numaish Chowrangi", 24.8717, 67.0346),
    Place("Gulistan-e-Jauhar (Jauhar Chowrangi)", 24.9207, 67.1298),
    Place("DHA Phase 5", 24.8050, 67.0570),
    Place("DHA Phase 6", 24.8000, 67.0650),
]

PLACES_BY_NAME = {p.name: p for p in PLACES}
