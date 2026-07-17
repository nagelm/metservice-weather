"""Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/nagelm/metservice-weather.
"""

from __future__ import annotations

from typing import Final


DOMAIN = "metservice_weather"
CONF_ATTRIBUTION = "Data provided by the MetService NZ weather service"
MANUFACTURER = "MetService"

# Onboarding option: when enabled, seasonal sensors (UV, fire danger, clothes
# drying) that MetService is not currently publishing are removed instead of
# staying in an always-unknown state, and re-created automatically once data
# resumes. Default off — see weather_current_conditions_sensors.py's
# `seasonal` field and sensor.py's async_setup_entry gating.
CONF_AUTO_HIDE_SEASONAL = "auto_hide_seasonal"

FIELD_DESCRIPTION = "wxPhraseLong"
FIELD_HUMIDITY = "relativeHumidity"
FIELD_PRESSURE = "pressureAltimeter"
FIELD_TEMP = "temperature"
FIELD_WINDDIR = "windDirection"
FIELD_WINDGUST = "windGust"
FIELD_WINDSPEED = "windSpeed"


CONDITION_MAP: Final[dict[str, str]] = {
    # Every newly detected entry should be added to this list, mapping to homeassistant's supported values from below.
    # These initial entries are as found on https://about.metservice.com/our-company/learning-centre/weather-icons-explained/
    "cloudy": "cloudy",
    "drizzle": "rainy",
    "few-showers": "rainy",
    "few-showers-night": "rainy",
    "fine": "sunny",
    "fog": "fog",
    "frost": "clear-night",
    "hail": "hail",
    "mostly-cloudy": "cloudy",
    "partly-cloudy": "partlycloudy",
    "partly-cloudy-night": "partlycloudy",
    "rain": "pouring",
    "showers": "rainy",
    "snow": "snowy",
    "thunder": "lightning",
    "wind-rain": "pouring",
    "rain-wind": "pouring",
    "windy": "windy",
}

LOCATIONS = [
    {
        "label": "Dargaville",
        "value": "/towns-cities/regions/northland/locations/dargaville",
    },
    {"label": "Kaikohe", "value": "/rural/regions/northland/locations/kaikohe"},
    {"label": "Kaitaia", "value": "/towns-cities/regions/northland/locations/kaitaia"},
    {
        "label": "Kaitaia Airport",
        "value": "/towns-cities/regions/northland/locations/kaitaia-airport",
    },
    {
        "label": "Kerikeri",
        "value": "/towns-cities/regions/northland/locations/kerikeri",
    },
    {"label": "Paihia", "value": "/towns-cities/regions/northland/locations/paihia"},
    {"label": "Russell", "value": "/towns-cities/regions/northland/locations/russell"},
    {
        "label": "Whangārei",
        "value": "/towns-cities/regions/northland/locations/whangarei",
    },
    {
        "label": "Auckland Central",
        "value": "/towns-cities/regions/auckland/locations/auckland",
    },
    {"label": "Hunua", "value": "/towns-cities/regions/auckland/locations/hunua"},
    {"label": "Kumeu", "value": "/rural/regions/auckland/locations/kumeu"},
    {"label": "Manukau", "value": "/towns-cities/regions/auckland/locations/manukau"},
    {
        "label": "North Shore",
        "value": "/towns-cities/regions/auckland/locations/north-shore",
    },
    {"label": "Pukekohe", "value": "/rural/regions/auckland/locations/pukekohe"},
    {"label": "Pōkeno", "value": "/towns-cities/regions/auckland/locations/pokeno"},
    {"label": "Tuakau", "value": "/towns-cities/regions/auckland/locations/tuakau"},
    {
        "label": "Waiheke Island",
        "value": "/towns-cities/regions/auckland/locations/waiheke-island",
    },
    {
        "label": "Waitakere",
        "value": "/towns-cities/regions/auckland/locations/waitakere",
    },
    {"label": "Warkworth", "value": "/rural/regions/auckland/locations/warkworth"},
    {"label": "Cambridge", "value": "/rural/regions/waikato/locations/cambridge"},
    {"label": "Hamilton", "value": "/towns-cities/regions/waikato/locations/hamilton"},
    {"label": "Huntly", "value": "/rural/regions/waikato/locations/huntly"},
    {"label": "Matamata", "value": "/rural/regions/waikato/locations/matamata"},
    {"label": "Morrinsville", "value": "/rural/regions/waikato/locations/morrinsville"},
    {"label": "Ngāruawāhia", "value": "/rural/regions/waikato/locations/ngaruawahia"},
    {"label": "Paeroa", "value": "/rural/regions/waikato/locations/paeroa"},
    {"label": "Putāruru", "value": "/rural/regions/waikato/locations/putaruru"},
    {"label": "Raglan", "value": "/rural/regions/waikato/locations/raglan"},
    {"label": "Te Aroha", "value": "/rural/regions/waikato/locations/te-aroha"},
    {"label": "Te Awamutu", "value": "/rural/regions/waikato/locations/te-awamutu"},
    {"label": "Tokoroa", "value": "/towns-cities/regions/waikato/locations/tokoroa"},
    {"label": "Piopio", "value": "/rural/regions/waitomo/locations/piopio"},
    {"label": "Te Kuiti", "value": "/towns-cities/regions/waitomo/locations/te-kuiti"},
    {"label": "Waitomo", "value": "/rural/regions/waitomo/locations/waitomo"},
    {"label": "Thames", "value": "/towns-cities/regions/coromandel/locations/thames"},
    {"label": "Waihi", "value": "/rural/regions/coromandel/locations/waihi"},
    {
        "label": "Waikawau Bay",
        "value": "/rural/regions/coromandel/locations/waikawau-bay",
    },
    {"label": "Whangamatā", "value": "/rural/regions/coromandel/locations/whangamata"},
    {
        "label": "Whitianga",
        "value": "/towns-cities/regions/coromandel/locations/whitianga",
    },
    {
        "label": "Ngongotahā",
        "value": "/towns-cities/regions/rotorua/locations/ngongotaha",
    },
    {"label": "Rotorua", "value": "/towns-cities/regions/rotorua/locations/rotorua"},
    {"label": "Katikati", "value": "/rural/regions/bay-of-plenty/locations/katikati"},
    {"label": "Kawerau", "value": "/rural/regions/bay-of-plenty/locations/kawerau"},
    {
        "label": "Mount Maunganui",
        "value": "/towns-cities/regions/bay-of-plenty/locations/mount-maunganui",
    },
    {"label": "Opotiki", "value": "/rural/regions/bay-of-plenty/locations/opotiki"},
    {"label": "Papamoa", "value": "/rural/regions/bay-of-plenty/locations/papamoa"},
    {
        "label": "Tauranga",
        "value": "/towns-cities/regions/bay-of-plenty/locations/tauranga",
    },
    {"label": "Te Puke", "value": "/rural/regions/bay-of-plenty/locations/te-puke"},
    {
        "label": "Whakatāne",
        "value": "/towns-cities/regions/bay-of-plenty/locations/whakatane",
    },
    {"label": "Ōhope", "value": "/towns-cities/regions/bay-of-plenty/locations/ohope"},
    {
        "label": "Ōmokoroa",
        "value": "/towns-cities/regions/bay-of-plenty/locations/omokoroa",
    },
    {"label": "Taupō", "value": "/towns-cities/regions/taupo/locations/taupo"},
    {
        "label": "Taupō Airport",
        "value": "/towns-cities/regions/taupo/locations/taupo-airport",
    },
    {"label": "Tūrangi", "value": "/rural/regions/taupo/locations/turangi"},
    {"label": "Gisborne", "value": "/towns-cities/regions/gisborne/locations/gisborne"},
    {"label": "Ruatoria", "value": "/rural/regions/gisborne/locations/ruatoria"},
    {
        "label": "Eastern Rangitaiki",
        "value": "/rural/regions/hawkes-bay/locations/eastern-rangitaiki",
    },
    {
        "label": "Hastings",
        "value": "/towns-cities/regions/hawkes-bay/locations/hastings",
    },
    {
        "label": "Havelock North",
        "value": "/towns-cities/regions/hawkes-bay/locations/havelock-north",
    },
    {"label": "Mahia", "value": "/rural/regions/hawkes-bay/locations/mahia"},
    {"label": "Napier", "value": "/towns-cities/regions/hawkes-bay/locations/napier"},
    {
        "label": "Napier Airport",
        "value": "/towns-cities/regions/hawkes-bay/locations/napier-airport",
    },
    {"label": "Waipukurau", "value": "/rural/regions/hawkes-bay/locations/waipukurau"},
    {"label": "Wairoa", "value": "/rural/regions/hawkes-bay/locations/wairoa"},
    {"label": "Eltham", "value": "/rural/regions/taranaki/locations/eltham"},
    {"label": "Hāwera", "value": "/rural/regions/taranaki/locations/hawera"},
    {"label": "Inglewood", "value": "/rural/regions/taranaki/locations/inglewood"},
    {
        "label": "New Plymouth",
        "value": "/towns-cities/regions/taranaki/locations/new-plymouth",
    },
    {
        "label": "New Plymouth Airport",
        "value": "/towns-cities/regions/taranaki/locations/new-plymouth-airport",
    },
    {"label": "Opunake", "value": "/rural/regions/taranaki/locations/opunake"},
    {"label": "Stratford", "value": "/rural/regions/taranaki/locations/stratford"},
    {
        "label": "Taumarunui",
        "value": "/towns-cities/regions/taumarunui/locations/taumarunui",
    },
    {"label": "Ohakune", "value": "/rural/regions/taihape/locations/ohakune"},
    {"label": "Waiouru", "value": "/rural/regions/taihape/locations/waiouru"},
    {
        "label": "Whanganui",
        "value": "/towns-cities/regions/wanganui/locations/wanganui",
    },
    {
        "label": "Whanganui Airport",
        "value": "/towns-cities/regions/wanganui/locations/wanganui-airport",
    },
    {"label": "Feilding", "value": "/rural/regions/manawatu/locations/feilding"},
    {"label": "Hunterville", "value": "/rural/regions/manawatu/locations/hunterville"},
    {"label": "Ohakea", "value": "/rural/regions/manawatu/locations/ohakea"},
    {
        "label": "Palmerston North",
        "value": "/towns-cities/regions/manawatu/locations/palmerston-north",
    },
    {
        "label": "Palmerston North Airport",
        "value": "/towns-cities/regions/manawatu/locations/palmerston-north-airport",
    },
    {"label": "Carterton", "value": "/rural/regions/wairarapa/locations/carterton"},
    {"label": "Castlepoint", "value": "/rural/regions/wairarapa/locations/castlepoint"},
    {
        "label": "Dannevirke",
        "value": "/towns-cities/regions/wairarapa/locations/dannevirke",
    },
    {"label": "Featherston", "value": "/rural/regions/wairarapa/locations/featherston"},
    {
        "label": "Martinborough",
        "value": "/rural/regions/wairarapa/locations/martinborough",
    },
    {
        "label": "Masterton",
        "value": "/towns-cities/regions/wairarapa/locations/masterton",
    },
    {
        "label": "Levin",
        "value": "/towns-cities/regions/kapiti-horowhenua/locations/levin",
    },
    {
        "label": "Paraparaumu",
        "value": "/towns-cities/regions/kapiti-horowhenua/locations/paraparaumu",
    },
    {"label": "Te Horo", "value": "/rural/regions/kapiti-horowhenua/locations/te-horo"},
    {
        "label": "Waikanae",
        "value": "/towns-cities/regions/kapiti-horowhenua/locations/waikanae",
    },
    {"label": "Ōtaki", "value": "/rural/regions/kapiti-horowhenua/locations/otaki"},
    {"label": "Judgeford", "value": "/rural/regions/wellington/locations/judgeford"},
    {
        "label": "Lower Hutt",
        "value": "/towns-cities/regions/wellington/locations/lower-hutt",
    },
    {
        "label": "Lyall Bay",
        "value": "/towns-cities/regions/wellington/locations/lyall-bay",
    },
    {
        "label": "Ohariu Valley",
        "value": "/rural/regions/wellington/locations/ohariu-valley",
    },
    {"label": "Porirua", "value": "/towns-cities/regions/wellington/locations/porirua"},
    {
        "label": "Upper Hutt",
        "value": "/towns-cities/regions/wellington/locations/upper-hutt",
    },
    {
        "label": "Wainuiomata",
        "value": "/towns-cities/regions/wellington/locations/wainuiomata",
    },
    {
        "label": "Wellington Central",
        "value": "/towns-cities/regions/wellington/locations/wellington",
    },
    {
        "label": "Blenheim",
        "value": "/towns-cities/regions/marlborough/locations/blenheim",
    },
    {
        "label": "Kaikōura",
        "value": "/towns-cities/regions/marlborough/locations/kaikoura",
    },
    {
        "label": "Kaikōura Airport",
        "value": "/towns-cities/regions/marlborough/locations/kaikoura-airport",
    },
    {"label": "Picton", "value": "/rural/regions/marlborough/locations/picton"},
    {"label": "Golden Bay", "value": "/rural/regions/nelson"},
    {"label": "Motueka", "value": "/towns-cities/regions/nelson/locations/motueka"},
    {"label": "Murchison", "value": "/rural/regions/nelson/locations/murchison"},
    {"label": "Nelson", "value": "/towns-cities/regions/nelson/locations/nelson"},
    {"label": "Richmond", "value": "/towns-cities/regions/nelson/locations/richmond"},
    {"label": "St Arnaud", "value": "/rural/regions/nelson/locations/st-arnaud"},
    {"label": "Takaka", "value": "/rural/regions/nelson/locations/takaka"},
    {"label": "Reefton", "value": "/towns-cities/regions/buller/locations/reefton"},
    {"label": "Westport", "value": "/towns-cities/regions/buller/locations/westport"},
    {"label": "Franz Josef", "value": "/rural/regions/westland/locations/franz-josef"},
    {
        "label": "Greymouth",
        "value": "/towns-cities/regions/westland/locations/greymouth",
    },
    {"label": "Haast", "value": "/rural/regions/westland/locations/haast"},
    {"label": "Hokitika", "value": "/towns-cities/regions/westland/locations/hokitika"},
    {
        "label": "Ashburton",
        "value": "/towns-cities/regions/canterbury-plains/locations/ashburton",
    },
    {
        "label": "Darfield",
        "value": "/rural/regions/canterbury-plains/locations/darfield",
    },
    {"label": "Kaiapoi", "value": "/rural/regions/canterbury-plains/locations/kaiapoi"},
    {"label": "Methven", "value": "/rural/regions/canterbury-plains/locations/methven"},
    {"label": "Pegasus", "value": "/rural/regions/canterbury-plains/locations/pegasus"},
    {"label": "Rakaia", "value": "/rural/regions/canterbury-plains/locations/rakaia"},
    {"label": "Temuka", "value": "/rural/regions/canterbury-plains/locations/temuka"},
    {
        "label": "Timaru",
        "value": "/towns-cities/regions/canterbury-plains/locations/timaru",
    },
    {"label": "Waimate", "value": "/rural/regions/canterbury-plains/locations/waimate"},
    {"label": "Waipara", "value": "/rural/regions/canterbury-plains/locations/waipara"},
    {
        "label": "Culverden",
        "value": "/rural/regions/canterbury-high-country/locations/culverden",
    },
    {
        "label": "Hanmer Springs",
        "value": "/rural/regions/canterbury-high-country/locations/hanmer-springs",
    },
    {
        "label": "Mount Cook",
        "value": "/towns-cities/regions/canterbury-high-country/locations/mount-cook",
    },
    {
        "label": "Omarama",
        "value": "/rural/regions/canterbury-high-country/locations/omarama",
    },
    {
        "label": "Twizel",
        "value": "/rural/regions/canterbury-high-country/locations/twizel",
    },
    {
        "label": "Banks Peninsula",
        "value": "/towns-cities/regions/christchurch/locations/banks-peninsula",
    },
    {
        "label": "Christchurch Central",
        "value": "/towns-cities/regions/christchurch/locations/christchurch",
    },
    {
        "label": "Eastern Suburbs",
        "value": "/towns-cities/regions/christchurch/locations/eastern-suburbs",
    },
    {"label": "Hilltop", "value": "/rural/regions/christchurch/locations/hill-top"},
    {"label": "Lincoln", "value": "/rural/regions/christchurch/locations/lincoln"},
    {"label": "Marshland", "value": "/rural/regions/christchurch/locations/marshlands"},
    {
        "label": "Port Hills",
        "value": "/towns-cities/regions/christchurch/locations/port-hills",
    },
    {
        "label": "Prebbleton",
        "value": "/towns-cities/regions/christchurch/locations/prebbleton",
    },
    {
        "label": "Rolleston",
        "value": "/towns-cities/regions/christchurch/locations/rolleston",
    },
    {"label": "Oamaru", "value": "/towns-cities/regions/north-otago/locations/oamaru"},
    {
        "label": "Oamaru Airport",
        "value": "/towns-cities/regions/north-otago/locations/oamaru-airport",
    },
    {
        "label": "Alexandra",
        "value": "/towns-cities/regions/central-otago/locations/alexandra",
    },
    {"label": "Cromwell", "value": "/rural/regions/central-otago/locations/cromwell"},
    {"label": "Dunedin", "value": "/towns-cities/regions/dunedin/locations/dunedin"},
    {
        "label": "Leith Saddle",
        "value": "/towns-cities/regions/dunedin/locations/leith-saddle",
    },
    {"label": "Middlemarch", "value": "/rural/regions/dunedin/locations/middlemarch"},
    {"label": "Mosgiel", "value": "/towns-cities/regions/dunedin/locations/mosgiel"},
    {
        "label": "Port Chalmers",
        "value": "/towns-cities/regions/dunedin/locations/port-chalmers",
    },
    {"label": "Waitati", "value": "/rural/regions/dunedin/locations/waitati"},
    {"label": "Balclutha", "value": "/rural/regions/clutha/locations/balclutha"},
    {"label": "Nugget Point", "value": "/rural/regions/clutha/locations/nugget-point"},
    {
        "label": "Glenorchy",
        "value": "/rural/regions/southern-lakes/locations/glenorchy",
    },
    {
        "label": "Lake Hayes",
        "value": "/rural/regions/southern-lakes/locations/lake-hayes",
    },
    {
        "label": "Queenstown",
        "value": "/towns-cities/regions/southern-lakes/locations/queenstown",
    },
    {
        "label": "Wānaka",
        "value": "/towns-cities/regions/southern-lakes/locations/wanaka",
    },
    {"label": "Gore", "value": "/towns-cities/regions/southland/locations/gore"},
    {
        "label": "Invercargill",
        "value": "/towns-cities/regions/southland/locations/invercargill",
    },
    {"label": "Lumsden", "value": "/rural/regions/southland/locations/lumsden"},
    {
        "label": "Milford Sound",
        "value": "/towns-cities/regions/southland/locations/milford-sound",
    },
    {
        "label": "Stewart Island",
        "value": "/rural/regions/southland/locations/stewart-island",
    },
    {"label": "Te Anau", "value": "/rural/regions/southland/locations/te-anau"},
]


PUBLIC_URL = "https://www.metservice.com/publicData/webdata"
PUBLIC_WARNINGS_URL = "https://www.metservice.com/publicData/webdata/warnings-service"
API_METRIC: Final = "metric"
API_URL_METRIC: Final = "m"
DEFAULT_LOCATION = "/towns-cities/regions/bay-of-plenty/locations/tauranga"

TEMPUNIT = "temperature"
LENGTHUNIT = "length"
SPEEDUNIT = "speed"
PRESSUREUNIT = "pressure"
