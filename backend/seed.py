"""Demo data for Denizli: districts, users, customers, suppliers, fleet, shipments and visits."""

import asyncio
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from backend.config import settings
from backend.database import SessionLocal, init_db
from backend.models import (
    Company,
    CompanyLocation,
    Entity,
    EntityCategory,
    EntityStatus,
    EntityType,
    FieldVisit,
    FleetIntegration,
    LocationKind,
    Region,
    Role,
    Shipment,
    ShipmentStatus,
    TelematicsProvider,
    User,
    Vehicle,
    VehicleStatus,
    VehicleType,
    VisitType,
)
from backend.security import hash_password
from services.telematics.crypto import encrypt_credentials
from services.telematics.registry import adapter_for
from services.telematics.sync import store_positions

DEMO_PASSWORD = "admin123"

DISTRICTS = [
    ("Merkezefendi", "MRK"),
    ("Pamukkale", "PAM"),
    ("Honaz", "HNZ"),
    ("Sarayköy", "SRK"),
    ("Çivril", "CVR"),
    ("Tavas", "TVS"),
    ("Acıpayam", "ACP"),
]

# key, name, type, category, address, lat, lng, phone, balance, region code
ENTITIES = [
    ("saraylar", "Saraylar Market", EntityType.customer, EntityCategory.vip,
     "Saraylar Mah., Merkezefendi / Denizli", 37.7760, 29.0810, "02582110001", 118000, "MRK"),
    ("sumer", "Sümer Tekstil Mağazası", EntityType.customer, EntityCategory.active,
     "Sümer Mah., Merkezefendi / Denizli", 37.7640, 29.0630, "02582110002", 36500, "MRK"),
    ("kinikli", "Kınıklı Kafe Zinciri", EntityType.customer, EntityCategory.active,
     "Kınıklı Mah., Pamukkale / Denizli", 37.7440, 29.1010, "02582110003", 12400, "PAM"),
    ("karahayit", "Karahayıt Termal Otel", EntityType.customer, EntityCategory.vip,
     "Karahayıt Mah., Pamukkale / Denizli", 37.9620, 29.1000, "02582110004", 94000, "PAM"),
    ("honaz", "Honaz Yapı Market", EntityType.customer, EntityCategory.potential,
     "Honaz / Denizli", 37.7590, 29.2700, "02582110005", 0, "HNZ"),
    ("tavas", "Tavas Kooperatif Market", EntityType.customer, EntityCategory.active,
     "Tavas / Denizli", 37.5730, 29.0700, "02582110006", 7800, "TVS"),
    ("acipayam", "Acıpayam Süt Ürünleri", EntityType.customer, EntityCategory.potential,
     "Acıpayam / Denizli", 37.4260, 29.3500, "02582110007", 0, "ACP"),
    ("civril_musteri", "Çivril Toptan Gıda", EntityType.customer, EntityCategory.active,
     "Çivril / Denizli", 38.3010, 29.7390, "02582110008", 21000, "CVR"),
    ("saraykoy_iplik", "Sarayköy Pamuk İplik", EntityType.supplier, EntityCategory.raw_material,
     "Sarayköy / Denizli", 37.9270, 28.9260, "02582110009", 42000, "SRK"),
    ("honaz_mermer", "Honaz Mermer Hammadde", EntityType.supplier, EntityCategory.raw_material,
     "Honaz / Denizli", 37.7480, 29.2550, "02582110010", 15500, "HNZ"),
    ("civril_meyve", "Çivril Meyve Tedarik", EntityType.supplier, EntityCategory.raw_material,
     "Çivril / Denizli", 38.2950, 29.7250, "02582110011", 9800, "CVR"),
    ("rakip", "Ege Dağıtım (Rakip)", EntityType.competitor, EntityCategory.active,
     "Gümüşler Mah., Merkezefendi / Denizli", 37.7700, 29.0560, "02582110012", 0, "MRK"),
    ("hal", "Denizli Toptancı Hali", EntityType.other, EntityCategory.active,
     "Sevindik Mah., Merkezefendi / Denizli", 37.7900, 29.0700, "02582110013", 0, "MRK"),
]

# name, kind, address, lat, lng, default depot, region code
LOCATIONS = [
    ("Genel Merkez", LocationKind.headquarters, "Saraylar Mah., Merkezefendi / Denizli",
     37.7830, 29.0940, False, "MRK"),
    ("Denizli Merkez Depo", LocationKind.depot, "Organize Sanayi Bölgesi / Denizli",
     37.8000, 29.0500, True, "MRK"),
    ("Pamukkale Şube", LocationKind.branch, "Kınıklı Mah., Pamukkale / Denizli",
     37.7420, 29.1080, False, "PAM"),
]


async def backfill_yesterday(db, integration: FleetIntegration) -> int:
    yesterday = datetime.now(settings.tz).date() - timedelta(days=1)
    since = datetime.combine(yesterday, time(7, 0), settings.tz).astimezone(timezone.utc)
    until = datetime.combine(yesterday, time(19, 0), settings.tz).astimezone(timezone.utc)
    points = await adapter_for(integration).fetch_positions(since, until)
    result = await store_positions(db, integration, points)
    await db.commit()
    return result.inserted


async def seed() -> None:
    await init_db()
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.username == "admin"))
        if existing is not None:
            print("Veritabanı dolu, seed atlandı. Sıfırlamak için harita3000.db dosyasını silin.")
            return

        regions = {code: Region(name=name, code=code) for name, code in DISTRICTS}
        db.add_all(regions.values())
        await db.flush()

        password = hash_password(DEMO_PASSWORD)
        home = regions["MRK"].id
        admin = User(username="admin", hashed_password=password, role=Role.admin,
                     region_id=home, full_name="Demo Yönetici")
        logistics = User(username="lojistik", hashed_password=password, role=Role.logistics,
                         region_id=home, full_name="Demo Lojistik")
        marketer = User(username="pazarlamaci", hashed_password=password, role=Role.marketer,
                        region_id=home, full_name="Demo Pazarlamacı")
        driver = User(username="surucu", hashed_password=password, role=Role.driver,
                      region_id=home, full_name="Demo Sürücü")
        db.add_all([admin, logistics, marketer, driver])
        db.add(Company(name="Harita3000 Demo A.Ş.", tax_number="1234567890", phone="02582110000",
                       email="info@harita3000.example", address="Saraylar Mah., Merkezefendi / Denizli"))
        db.add_all(
            CompanyLocation(name=name, kind=kind, address=address, latitude=lat, longitude=lng,
                            is_default_depot=default, region_id=regions[code].id)
            for name, kind, address, lat, lng, default, code in LOCATIONS
        )
        await db.flush()

        entities: dict[str, Entity] = {}
        for index, (key, name, kind, category, address, lat, lng, phone, balance, code) in enumerate(ENTITIES, 1):
            entities[key] = Entity(
                name=name,
                type=kind,
                category=category,
                address=address,
                latitude=lat,
                longitude=lng,
                phone=phone,
                email=f"{key}@example.com",
                tax_number=f"20{index:08d}",
                current_balance=balance,
                status=EntityStatus.active,
                region_id=regions[code].id,
            )
        entities["unlocated"] = Entity(
            name="Adresi Bekleyen Cari",
            type=EntityType.customer,
            category=EntityCategory.potential,
            address="Koordinat girilmedi",
            phone="05001112233",
            email="bekleyen@example.com",
            tax_number="2099999999",
            current_balance=0,
            status=EntityStatus.inactive,
            region_id=home,
        )
        db.add_all(entities.values())
        await db.flush()

        van = Vehicle(plate_number="20 HRT 01", vehicle_type=VehicleType.van, max_weight_kg=1500,
                      max_volume_m3=8, current_status=VehicleStatus.on_route, region_id=home,
                      last_latitude=37.7800, last_longitude=29.0750)
        truck = Vehicle(plate_number="20 HRT 02", vehicle_type=VehicleType.truck, max_weight_kg=20000,
                        max_volume_m3=80, current_status=VehicleStatus.available, region_id=home,
                        last_latitude=37.8000, last_longitude=29.0500)
        broken = Vehicle(plate_number="20 HRT 03", vehicle_type=VehicleType.truck, max_weight_kg=18000,
                         max_volume_m3=70, current_status=VehicleStatus.maintenance,
                         region_id=regions["PAM"].id, last_latitude=37.8050, last_longitude=29.0550)
        minibus = Vehicle(plate_number="20 HRT 04", vehicle_type=VehicleType.minibus, max_weight_kg=900,
                          max_volume_m3=6, current_status=VehicleStatus.available,
                          region_id=regions["PAM"].id, last_latitude=37.7450, last_longitude=29.0980)
        simulator = FleetIntegration(provider=TelematicsProvider.simulator, name="Demo Simülatör",
                                     poll_interval_min=5, is_active=True,
                                     credentials_encrypted=encrypt_credentials({"use_roads": "true"}))
        db.add(simulator)
        await db.flush()
        van.integration_id, van.external_id = simulator.id, "SIM-01"
        minibus.integration_id, minibus.external_id = simulator.id, "SIM-04"
        db.add_all([van, truck, broken, minibus])
        await db.flush()

        today = datetime.now(settings.tz).date()
        yesterday = today - timedelta(days=1)
        db.add_all(
            [
                Shipment(entity_id=entities["saraylar"].id, vehicle_id=van.id, driver_id=driver.id,
                         status=ShipmentStatus.delivered, delivery_date=yesterday, notes="Dünkü tur",
                         items_json=[{"name": "İçecek kolisi", "quantity": 30, "unit": "koli"}]),
                Shipment(entity_id=entities["kinikli"].id, vehicle_id=van.id, driver_id=driver.id,
                         status=ShipmentStatus.delivered, delivery_date=yesterday, notes="Dünkü tur",
                         items_json=[{"name": "Kahve çekirdeği", "quantity": 8, "unit": "çuval"}]),
                Shipment(entity_id=entities["tavas"].id, vehicle_id=van.id, driver_id=driver.id,
                         status=ShipmentStatus.on_route, delivery_date=yesterday,
                         notes="Planlandı ama uğranmadı",
                         items_json=[{"name": "Kuru gıda", "quantity": 10, "unit": "koli"}]),
            ]
        )
        db.add_all(
            [
                Shipment(entity_id=entities["saraylar"].id, vehicle_id=van.id, driver_id=driver.id,
                         status=ShipmentStatus.on_route, delivery_date=today, notes="Sabah vardiyası",
                         items_json=[{"name": "İçecek kolisi", "quantity": 40, "unit": "koli"}]),
                Shipment(entity_id=entities["sumer"].id, status=ShipmentStatus.pending,
                         delivery_date=today - timedelta(days=1), notes="Gecikmiş teslimat",
                         items_json=[{"name": "Askı ve ambalaj", "quantity": 25, "unit": "koli"}]),
                Shipment(entity_id=entities["kinikli"].id, vehicle_id=minibus.id, driver_id=driver.id,
                         status=ShipmentStatus.delivered, delivery_date=today, notes="Teslim alındı",
                         items_json=[{"name": "Kahve çekirdeği", "quantity": 12, "unit": "çuval"}]),
                Shipment(entity_id=entities["karahayit"].id, status=ShipmentStatus.pending,
                         delivery_date=today, notes="Otel mutfağı, 10:00 öncesi",
                         items_json=[{"name": "Donuk ürün", "quantity": 18, "unit": "koli"}]),
                Shipment(entity_id=entities["tavas"].id, status=ShipmentStatus.pending,
                         delivery_date=today + timedelta(days=2), notes="Haftalık sipariş",
                         items_json=[{"name": "Kuru gıda", "quantity": 30, "unit": "koli"}]),
            ]
        )

        db.add_all(
            [
                FieldVisit(user_id=marketer.id, entity_id=entities["saraylar"].id,
                           visit_type=VisitType.marketing,
                           check_in_time=datetime.combine(today, time(6, 0), tzinfo=timezone.utc),
                           check_out_time=datetime.combine(today, time(7, 0), tzinfo=timezone.utc),
                           notes="Raf düzeni konuşuldu",
                           form_data_json={"rakip_analizi": "Rakip fiyatı yüzde 5 daha düşük",
                                           "musteri_talebi": "Haftalık sevkiyat istiyor"}),
                FieldVisit(user_id=marketer.id, entity_id=entities["sumer"].id,
                           visit_type=VisitType.collection, notes="Öğleden sonra tahsilat planı",
                           form_data_json={"rakip_analizi": "", "musteri_talebi": "Vade uzatma talebi"}),
                FieldVisit(user_id=marketer.id, entity_id=entities["honaz"].id,
                           visit_type=VisitType.marketing,
                           check_in_time=datetime.combine(today, time(8, 0), tzinfo=timezone.utc),
                           notes="İlk tanışma ziyareti sürüyor",
                           form_data_json={"rakip_analizi": "", "musteri_talebi": "Fiyat listesi"}),
            ]
        )
        await db.commit()

        try:
            inserted = await backfill_yesterday(db, simulator)
            print(f"Dünün simülasyon izi yüklendi: {inserted} konum")
        except Exception as exc:
            await db.rollback()
            print(f"Dünün izi yüklenemedi ({exc}); zamanlayıcı bugünden itibaren veri toplayacak.")

    print("Seed tamamlandı (Denizli).")
    print("Giriş: admin, lojistik, pazarlamaci, surucu")
    print(f"Parola: {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
