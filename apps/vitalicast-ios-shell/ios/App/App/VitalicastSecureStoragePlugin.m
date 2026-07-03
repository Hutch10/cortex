#import <Foundation/Foundation.h>
#import <Capacitor/Capacitor.h>

CAP_PLUGIN(VitalicastSecureStoragePlugin, "VitalicastSecureStorage",
    CAP_PLUGIN_METHOD(isAvailable, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(createSecureRecord, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(appendAddendum, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(readSecureRecord, CAPPluginReturnPromise);
)
