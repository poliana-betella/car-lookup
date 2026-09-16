def classFactory(iface):
    from .car_lookup import CarLookupPlugin
    return CarLookupPlugin(iface)
