from __future__ import annotations

import re
from urllib.parse import quote

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.versioning import parse_version_from_filename


BASE_BUILD_ARCHIVE_ITEM = "OnesaUCEv2BaseBuild"
GAME_PACKS_ARCHIVE_ITEM = "onesaucev2system-game-packs"
BITLCD_ARCHIVE_ITEM = "onesauce-v2-lcd-marquee-packs"
SIMPLE_BLUE_ARCHIVE_ITEM = "simple-blue_202404"


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1000.0 or unit == "T":
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1000.0
    return f"{value:.1f}T"


def _size_to_bytes(size_label: str) -> int | None:
    value = size_label.strip().upper()
    if value == "UNKNOWN":
        return None
    multiplier = {
        "B": 1,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }
    unit = value[-1]
    number = value[:-1]
    if unit not in multiplier:
        return None
    try:
        return int(float(number) * multiplier[unit])
    except ValueError:
        return None


def _slugify(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _archive_download_url(archive_item: str, filename: str) -> str:
    return f"https://archive.org/download/{archive_item}/{quote(filename)}"


def _bitlcd_pack_name(filename: str) -> str:
    stem = filename.removesuffix(".zip")
    stem = re.sub(r"\s*v\d+\.\d+b\d+$", "", stem, flags=re.IGNORECASE).strip()
    stem = re.sub(r"(?i)\s*sys\s+spec\s*", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def _game_pack(name: str, version: str, size: str) -> ComponentSpec:
    filename = f"{name} {version}.zip"
    return ComponentSpec(
        key=f"gamepack_{_slugify(name)}",
        display_name=name,
        archive_item=GAME_PACKS_ARCHIVE_ITEM,
        filename=filename,
        download_url=_archive_download_url(GAME_PACKS_ARCHIVE_ITEM, filename),
        install_root=name,
        version_file_relpath=None,
        available_version=version,
        required=False,
        size_label=size,
        size_bytes=_size_to_bytes(size),
    )


def _bitlcd_marquee(filename: str, size: str) -> ComponentSpec:
    version = parse_version_from_filename(filename) or "unknown"
    display_name = _bitlcd_pack_name(filename)
    return ComponentSpec(
        key=f"bitlcd_{_slugify(display_name)}",
        display_name=display_name,
        archive_item=BITLCD_ARCHIVE_ITEM,
        filename=filename,
        download_url=_archive_download_url(BITLCD_ARCHIVE_ITEM, filename),
        install_root=display_name,
        version_file_relpath=None,
        available_version=version,
        required=False,
        size_label=size,
        size_bytes=_size_to_bytes(size),
    )


REQUIRED_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        key="onesauce",
        display_name="OnesaUCE",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="OneSauce v2.0b6.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "OneSauce v2.0b6.zip"),
        install_root="OneSauce",
        version_file_relpath="OneSauce/OneSauce version.txt",
        available_version="v2.0b6",
        size_label=_format_size(625001),
        size_bytes=625001,
    ),
    ComponentSpec(
        key="appdata",
        display_name="appdata",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="appdata v2.0b46.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "appdata v2.0b46.zip"),
        install_root="appdata",
        version_file_relpath="appdata/appdata version.txt",
        available_version="v2.0b46",
        size_label=_format_size(612065911),
        size_bytes=612065911,
    ),
    ComponentSpec(
        key="base_assets",
        display_name="base_assets",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="base_assets v2.0b18.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "base_assets v2.0b18.zip"),
        install_root="base_assets",
        version_file_relpath="base_assets/base_assets version.txt",
        available_version="v2.0b18",
        size_label=_format_size(4854699601),
        size_bytes=4854699601,
    ),
    ComponentSpec(
        key="content",
        display_name="content",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="content v2.0b2.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "content v2.0b2.zip"),
        install_root="content",
        version_file_relpath="content/content version.txt",
        available_version="v2.0b2",
        size_label=_format_size(31679),
        size_bytes=31679,
    ),
    ComponentSpec(
        key="docs",
        display_name="docs",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="docs v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "docs v2.0b5.zip"),
        install_root="docs",
        version_file_relpath="docs/docs version.txt",
        available_version="v2.0b5",
        size_label=_format_size(1817779),
        size_bytes=1817779,
    ),
    ComponentSpec(
        key="ha8800_background",
        display_name="ha8800_background",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_background v2.0b2.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_background v2.0b2.zip"),
        install_root="ha8800_background",
        version_file_relpath=None,
        available_version="v2.0b2",
        size_label=_format_size(605600),
        size_bytes=605600,
        versionless=True,
    ),
)


GAME_PACKS: tuple[ComponentSpec, ...] = (
    _game_pack("AmstradCPC", "v2.0b2", "3.3G"),
    _game_pack("AmstradGX4000", "v2.0b2", "86.6M"),
    _game_pack("Arcade", "v2.0b4", "15.1G"),
    _game_pack("Atari2600", "v2.0b2", "710.7M"),
    _game_pack("Atari5200", "v2.0b2", "148.2M"),
    _game_pack("Atari7800", "v2.0b2", "173.1M"),
    _game_pack("Atari800", "v2.0b2", "1.5G"),
    _game_pack("AtariLynx", "v2.0b2", "229.3M"),
    _game_pack("AtariST", "v2.0b2", "195.2M"),
    _game_pack("BallyAstrocade", "v2.0b2", "42.1M"),
    _game_pack("BandaiWonderswan", "v2.0b2", "411.7M"),
    _game_pack("BandaiWonderswanColor", "v2.0b2", "746.4M"),
    _game_pack("ColecoVision", "v2.0b2", "251.6M"),
    _game_pack("Commodore64", "v2.0b2", "11.3G"),
    _game_pack("CommodoreAmiga", "v2.0b2", "8.4G"),
    _game_pack("CommodoreAmigaCD32", "v2.0b2", "1.0G"),
    _game_pack("CommodoreCDTV", "v2.0b2", "287.1M"),
    _game_pack("CommodoreVIC-20", "v2.0b2", "141.6M"),
    _game_pack("Daphne", "v2.0b3", "85.2G"),
    _game_pack("EmersonArcadia2001", "v2.0b2", "4.8M"),
    _game_pack("EpochSuperCasetteVision", "v2.0b2", "154.3M"),
    _game_pack("FairchildChannelF", "v2.0b2", "51.1M"),
    _game_pack("GCEVectrex", "v2.0b2", "147.4M"),
    _game_pack("Jukebox", "v2.0b5", "7.6M"),
    _game_pack("MagnavoxOdyssey", "v2.0b2", "61.7M"),
    _game_pack("MattelIntellivision", "v2.0b2", "115.7M"),
    _game_pack("MicrosoftMSDOS", "v2.0b2", "2.1G"),
    _game_pack("MicrosoftMSX", "v2.0b2", "1.3G"),
    _game_pack("NECPC-8801", "v2.0b2", "800.9M"),
    _game_pack("NECPC-9801", "v2.0b2", "2.8G"),
    _game_pack("NECPCEngine", "v2.0b2", "762.8M"),
    _game_pack("NECPCEngineCD", "v2.0b2", "37.4G"),
    _game_pack("NECSuperGrafx", "v2.0b2", "56.8M"),
    _game_pack("NECTurboGrafx-16", "v2.0b2", "667.7M"),
    _game_pack("NECTurboGrafx-CD", "v2.0b2", "13.3G"),
    _game_pack("Nintendo DS", "v2.0b2", "4.4G"),
    _game_pack("Nintendo64", "v2.0b2", "6.7G"),
    _game_pack("NintendoEntertainmentSystem", "v2.0b2", "1.9G"),
    _game_pack("NintendoFamicon", "v2.0b2", "1.4G"),
    _game_pack("NintendoFamiconDiskSystem", "v2.0b2", "827.1M"),
    _game_pack("NintendoGame&Watch", "v2.0b2", "166.8M"),
    _game_pack("NintendoGameBoy", "v2.0b2", "1.9G"),
    _game_pack("NintendoGameBoyAdvance", "v2.0b2", "6.6G"),
    _game_pack("NintendoGameBoyColor", "v2.0b2", "2.5G"),
    _game_pack("NintendoPokemonMini", "v2.0b2", "55.6M"),
    _game_pack("NintendoVirtualBoy", "v2.0b2", "96.1M"),
    _game_pack("OpenBOR", "v2.0b3", "45.9G"),
    _game_pack("PICO-8", "v2.0b2", "245.0M"),
    _game_pack("Panasonic3DO", "v2.0b2", "14.2G"),
    _game_pack("SNES", "v2.0b2", "70.7G"),
    _game_pack("SNESProjNested", "v2.0b3", "2.1G"),
    _game_pack("SNKNeoGeoCD", "v2.0b2", "25.8G"),
    _game_pack("SNKNeoGeoPocketColor", "v2.0b2", "207.7M"),
    _game_pack("Sammy Atomiswave", "v2.0b2", "2.0G"),
    _game_pack("ScummVM", "v2.0b4", "17.4G"),
    _game_pack("Sega MSU-MD", "v2.0b2", "12.5G"),
    _game_pack("Sega Naomi", "v2.0b2", "14.6G"),
    _game_pack("Sega32X", "v2.0b2", "5.4G"),
    _game_pack("SegaCD", "v2.0b2", "47.1G"),
    _game_pack("SegaDreamcast", "v2.0b2", "131.8G"),
    _game_pack("SegaGameGear", "v2.0b2", "593.9M"),
    _game_pack("SegaGenesis", "v2.0b2", "3.8G"),
    _game_pack("SegaMasterSystem", "v2.0b2", "939.8M"),
    _game_pack("SegaSG-1000", "v2.0b2", "199.5M"),
    _game_pack("Sharp X68000", "v2.0b4", "3.5G"),
    _game_pack("SharpX1", "v2.0b2", "354.3M"),
    _game_pack("SinclairZXSpectrum", "v2.0b2", "440.7M"),
    _game_pack("SonyPSP", "v2.0b2", "105.2G"),
    _game_pack("SonyPSPMinis", "v2.0b2", "8.0G"),
    _game_pack("SonyPlaystation", "v2.0b2", "195.9G"),
    _game_pack("TIC-80", "v2.0b2", "57.4M"),
    _game_pack("ThompsonM05", "v2.0b2", "234.5M"),
    _game_pack("ThompsonT07", "v2.0b2", "134.7M"),
    _game_pack("ThompsonT08", "v2.0b2", "196.2M"),
    _game_pack("WataraSupervision", "v2.0b2", "133.5M"),
    _game_pack("WoWActionMax", "v2.0b2", "36.5M"),
)


BITLCD_MARQUEES: tuple[ComponentSpec, ...] = (
    _bitlcd_marquee("Amiga CD32 Sys Specv2.0b2.zip", "9.2M"),
    _bitlcd_marquee("Amiga Sys Specv2.0b3.zip", "3.8G"),
    _bitlcd_marquee("Amstrad CPC Sys Specv2.0b2.zip", "192.7M"),
    _bitlcd_marquee("Amstrad GX4000 Sys Specv2.0b2.zip", "1.3M"),
    _bitlcd_marquee("Atari 2600 Sys Specv2.0b2.zip", "22.0M"),
    _bitlcd_marquee("Atari 5200 Sys Specv2.0b2.zip", "3.9M"),
    _bitlcd_marquee("Atari 7800 Sys Specv2.0b2.zip", "6.2M"),
    _bitlcd_marquee("Atari Lynx Sys Specv2.0b2.zip", "6.0M"),
    _bitlcd_marquee("Atari ST Sys Specv2.0b2.zip", "43.0M"),
    _bitlcd_marquee("Bally Astrocade Sys Specv2.0b2.zip", "3.0M"),
    _bitlcd_marquee("Bandai Wonderswan Color Sys Specv2.0b2.zip", "4.6M"),
    _bitlcd_marquee("Bandai Wonderswan Sys Specv2.0b2.zip", "6.6M"),
    _bitlcd_marquee("Colecovision Sys Specv2.0b2.zip", "11.7M"),
    _bitlcd_marquee("Commodore Amiga CD32 Sys Specv2.0b2.zip", "10.7M"),
    _bitlcd_marquee("Commodore CDTV Sys Specv2.0b2.zip", "5.4M"),
    _bitlcd_marquee("Comodore 64 Sys Specv2.0b2.zip", "3.3G"),
    _bitlcd_marquee("Daphne 99 Sys Specv2.0b2.zip", "2.4M"),
    _bitlcd_marquee("Fairchild Channel F Sys Specv2.0b2.zip", "1.9M"),
    _bitlcd_marquee("GCE Vectrex Sys Specv2.0b2.zip", "2.3M"),
    _bitlcd_marquee("Jukebox Sys Spec Full Color v2.0b4.zip", "40.5M"),
    _bitlcd_marquee("Jukebox Sys Spec Standardized v2.0b6.zip", "1.0G"),
    _bitlcd_marquee("Light Gun Sys Specv2.0b2.zip", "119.8M"),
    _bitlcd_marquee("MAME Sys Specv2.0b2.zip", "8.6G"),
    _bitlcd_marquee("Magnavox Odyssey 2 Sys Specv2.0b2.zip", "17.4M"),
    _bitlcd_marquee("Mattel Intellivision Sys Specv2.0b2.zip", "9.1M"),
    _bitlcd_marquee("MenusandThemes v2.0b5.zip", "273.8M"),
    _bitlcd_marquee("Microsoft MSX Sys Specv2.0b2.zip", "60.0M"),
    _bitlcd_marquee("NEC TurboGrafx 16 Sys Specv2.0b2.zip", "4.6M"),
    _bitlcd_marquee("NEC TurbografxCD Sys Specv2.0b2.zip", "3.5M"),
    _bitlcd_marquee("NES Sys Specv2.0b2.zip", "1.6G"),
    _bitlcd_marquee("NeoGeo Pocket Color Sys Specv2.0b2.zip", "2.9M"),
    _bitlcd_marquee("Nintendo 64 Sys Specv2.0b2.zip", "1.0G"),
    _bitlcd_marquee("Nintendo DS v2.0b2.zip", "71.7M"),
    _bitlcd_marquee("Nintendo Famicom Sys Specv2.0b2.zip", "13.0M"),
    _bitlcd_marquee("Nintendo Game Boy Sys Specv2.0b2.zip", "77.7M"),
    _bitlcd_marquee("Nintendo GameBoy Advanced Sys Specv2.0b2.zip", "3.3G"),
    _bitlcd_marquee("Nintendo GameBoy Color Sys Specv2.0b2.zip", "55.2M"),
    _bitlcd_marquee("Nintendo Pokeman Mini Sys Specv2.0b2.zip", "2.3M"),
    _bitlcd_marquee("Nintendo Satellaview Sys Specv2.0b2.zip", "74.5M"),
    _bitlcd_marquee("Nintendo Super Famicom Sys Specv2.0b2.zip", "37.2M"),
    _bitlcd_marquee("Nintendo Virtual Boy Sys Specv2.0b2.zip", "1.4M"),
    _bitlcd_marquee("Open BOR Sys Specv2.0b3.zip", "91.0M"),
    _bitlcd_marquee("Panasonic 3DO Sys Specv2.0b2.zip", "11.8M"),
    _bitlcd_marquee("Playstation Minis Sys Specv2.0b2.zip", "20.8M"),
    _bitlcd_marquee("SNES Sys Specv2.0b2.zip", "6.3G"),
    _bitlcd_marquee("SNK NeoGeo Sys Specv2.0b2.zip", "5.0M"),
    _bitlcd_marquee("ScummVM Sys Specv2.0b3.zip", "18.9M"),
    _bitlcd_marquee("Sega CD Sys Specv2.0b2.zip", "14.8M"),
    _bitlcd_marquee("Sega Dreamcast Sys Specv2.0b2.zip", "38.2M"),
    _bitlcd_marquee("Sega Game Gear Sys Specv2.0b2.zip", "19.6M"),
    _bitlcd_marquee("Sega Genesis Sys Specv2.0b2.zip", "94.9M"),
    _bitlcd_marquee("Sega MSU-MD v2.0b2.zip", "967.3M"),
    _bitlcd_marquee("Sega Master System Sys Specv2.0b2.zip", "33.1M"),
    _bitlcd_marquee("Sega SG1000 Sys Specv2.0b2.zip", "9.3M"),
    _bitlcd_marquee("Sega32X Sys Specv2.0b2.zip", "5.0M"),
    _bitlcd_marquee("Sinclair ZX Sys Specv2.0b2.zip", "127.7M"),
    _bitlcd_marquee("Sony PSP Sys Specv2.0b2.zip", "96.2M"),
    _bitlcd_marquee("Sony Playstation Sys Specv2.0b2.zip", "5.0G"),
    _bitlcd_marquee("TIC-80 Sys Specv2.0b2.zip", "41.6M"),
    _bitlcd_marquee("Thomson MO5 Sys Specv2.0b2.zip", "49.4M"),
    _bitlcd_marquee("Thomson TO7 Sys Specv2.0b2.zip", "14.0M"),
    _bitlcd_marquee("Thomson TO8 Sys Specv2.0b2.zip", "43.4M"),
)

OPTIONAL_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        key="optional_simple_blue",
        display_name="Simple Blue",
        archive_item=SIMPLE_BLUE_ARCHIVE_ITEM,
        filename="Simple Blue v2.0b5.zip",
        download_url=_archive_download_url(SIMPLE_BLUE_ARCHIVE_ITEM, "Simple Blue v2.0b5.zip"),
        install_root="base_assets/layouts/Simple Blue",
        version_file_relpath="base_assets/layouts/Simple Blue/Simple Blue version.txt",
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(14861755847),
        size_bytes=14861755847,
        component_type="Theme",
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_attract",
        display_name="Attract Mode Videos",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver Attract v2.0b6.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver Attract v2.0b6.zip"),
        install_root="ha8800_screensaver Attract",
        version_file_relpath=None,
        available_version="v2.0b6",
        required=False,
        size_label=_format_size(2396547027),
        size_bytes=2396547027,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_num_a",
        display_name="Jukebox Videos #-A",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver #-A v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver #-A v2.0b5.zip"),
        install_root="ha8800_screensaver #-A",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(25862052731),
        size_bytes=25862052731,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_b_c",
        display_name="Jukebox Videos B-C",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver B-C v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver B-C v2.0b5.zip"),
        install_root="ha8800_screensaver B-C",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(34791947148),
        size_bytes=34791947148,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_d_f",
        display_name="Jukebox Videos D-F",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver D-F v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver D-F v2.0b5.zip"),
        install_root="ha8800_screensaver D-F",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(30809116275),
        size_bytes=30809116275,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_g_j",
        display_name="Jukebox Videos G-J",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver G-J v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver G-J v2.0b5.zip"),
        install_root="ha8800_screensaver G-J",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(33070953259),
        size_bytes=33070953259,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_k_mg",
        display_name="Jukebox Videos K-Mg",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver K-Mg v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver K-Mg v2.0b5.zip"),
        install_root="ha8800_screensaver K-Mg",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(36121227143),
        size_bytes=36121227143,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_p_s",
        display_name="Jukebox Videos P-S",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver P-S v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver P-S v2.0b5.zip"),
        install_root="ha8800_screensaver P-S",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(45156104669),
        size_bytes=45156104669,
        component_type="Videos",
        versionless=True,
    ),
    ComponentSpec(
        key="optional_ha8800_screensaver_t_z",
        display_name="Jukebox Videos T-Z",
        archive_item=BASE_BUILD_ARCHIVE_ITEM,
        filename="ha8800_screensaver T-Z v2.0b5.zip",
        download_url=_archive_download_url(BASE_BUILD_ARCHIVE_ITEM, "ha8800_screensaver T-Z v2.0b5.zip"),
        install_root="ha8800_screensaver T-Z",
        version_file_relpath=None,
        available_version="v2.0b5",
        required=False,
        size_label=_format_size(30158290798),
        size_bytes=30158290798,
        component_type="Videos",
        versionless=True,
    ),
)
