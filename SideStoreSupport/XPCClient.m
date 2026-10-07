//
//  XPCClient.m
//  AltStore
//
//  Created by s s on 2025/7/20.
//  Copyright © 2025 SideStore. All rights reserved.
//
#include "XPCServer.h"
#include "../LiveContainer/utils.h"
#include "../LiveContainer/LCSharedUtils.h"
@import UIKit;

@interface SideStoreClient(Swift)
- (void)performRefreshForRealWithIdentifier:(NSString*)identifier
                            mangledTypeName:(NSString*)mangledTypeName
                                     server:(id <RefreshServer> _Nonnull)server;

@end

static LiveProcessSideStoreHandler* handler = nil;
void installSideStoreHooks(void);

@protocol V3CommandService
+ (void)execute:(NSData *)request reply:(void (^)(NSData *))reply;
@end

@implementation SideStoreClient
- (void)v3Execute:(NSData *)request reply:(void (^)(NSData *))reply {
    Class<V3CommandService> service = (Class<V3CommandService>)NSClassFromString(@"V3SideStoreService");
    if (service && [(id)service respondsToSelector:@selector(execute:reply:)]) {
        [service execute:request reply:reply];
    } else {
        reply([NSData data]);
    }
}


+ (SideStoreClient*)shared {
    static SideStoreClient* sharedClient = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        sharedClient = [SideStoreClient new];
    });

    return sharedClient;
}

+ (void)load {
    if(!NSUserDefaults.isSideStore) return;
    
    installSideStoreHooks();
    
    if(!NSUserDefaults.isLiveProcess) return;
    
    handler = [PrivClass(LiveProcessSideStoreHandler) shared];
    installSideStoreNotificationHooks();
    handler.connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RefreshClient)];
    handler.connection.exportedObject = SideStoreClient.shared;

    [[NSNotificationCenter defaultCenter] addObserver:self
                                             selector:@selector(appDidFinishLaunching:)
                                                 name:UIApplicationDidFinishLaunchingNotification
                                               object:nil];
}

// Implement the callback method
+ (void)appDidFinishLaunching:(NSNotification *)notification {
    NSDictionary *launchOptions = notification.userInfo;
    [handler.server finishedLaunching];
}

- (void) relaunchLC {
    [LCSharedUtils launchToGuestAppWithClassicMode:0];
}

- (void)refreshAllAppsWithIdentifier:(NSString*)identifier mangledTypeName:(NSString *)mangledTypeName refreshRunID:(NSString* _Nullable)refreshRunID {
    if(!handler) {
        return;
    }
    // V3_RUNTIME_SHARED_REFRESH_STORE_V1: the run ID, the previous verification
    // manifest and the host-handoff record form the host/service contract, so
    // they are cleared and stamped in the one runtime App Group the host
    // published. A fixed suite name would clear a store the embedded service
    // never writes, leaving the previous run's manifest to match a new run.
    // +[NSUserDefaults initWithSuiteName:] accepts any name and silently writes
    // the process's own domain when the suite is not a group this build is
    // entitled to, so the container is proven openable first. Otherwise the
    // stamps would land where the service can never read them.
    const char *runtimeAppGroup = getenv("LC_V3_INHERITED_APP_GROUP");
    NSString *runtimeAppGroupID = (runtimeAppGroup != NULL && runtimeAppGroup[0] != '\0')
        ? [NSString stringWithUTF8String:runtimeAppGroup] : nil;
    BOOL runtimeAppGroupOpenable = runtimeAppGroupID.length > 0 &&
        [NSFileManager.defaultManager containerURLForSecurityApplicationGroupIdentifier:runtimeAppGroupID] != nil;
    NSUserDefaults *defaults = runtimeAppGroupOpenable
        ? [[NSUserDefaults alloc] initWithSuiteName:runtimeAppGroupID] : nil;
    if (defaults == nil) {
        NSLog(@"[LIVE_CONTAINER_REFRESH] RESULT_STORE_UNAVAILABLE reason=runtime_app_group_unresolved");
    } else {
        [defaults removeObjectForKey:@"liveContainerAutoRefreshVerification"];
        [defaults removeObjectForKey:@"liveContainerAutoRefreshHostHandoff"];
        [defaults removeObjectForKey:@"liveContainerAutoRefreshHostHandoffRunID"];
        if (refreshRunID.length) [defaults setObject:refreshRunID forKey:@"liveContainerAutoRefreshExpectedRunID"];
        else [defaults removeObjectForKey:@"liveContainerAutoRefreshExpectedRunID"];
    }
    [self performRefreshForRealWithIdentifier:identifier mangledTypeName:mangledTypeName server:handler.server];
}

@end
