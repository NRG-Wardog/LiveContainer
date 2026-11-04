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
- (void)reportHostRefreshUnavailable:(NSString *)runID admissionID:(NSString *)admissionID server:(id<RefreshServer>)server;

@end

static LiveProcessSideStoreHandler* handler = nil;
void installSideStoreHooks(void);

@protocol V3CommandService
+ (void)execute:(NSData *)request reply:(void (^)(NSData *))reply;
+ (void)refreshForHost:(NSString *)runID
           admissionID:(NSString *)admissionID
              progress:(void (^)(double))progress
            completion:(void (^)(NSString * _Nullable, NSData * _Nullable))completion;
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
    // Uncorrelated legacy dispatch is never permitted to claim a host admission.
    if (handler) [handler.server finish:@"Host refresh requires an admission identity."];
}

- (void)refreshAllAppsWithIdentifier:(NSString*)identifier mangledTypeName:(NSString *)mangledTypeName refreshRunID:(NSString* _Nonnull)refreshRunID admissionID:(NSString* _Nonnull)admissionID {
    if(!handler) {
        return;
    }
    // V3_DIRECT_HOST_REFRESH_V1: only the service with the explicit admission
    // may clear state or start the canonical backend. No private AppIntent run.
    Class<V3CommandService> service = (Class<V3CommandService>)NSClassFromString(@"V3SideStoreService");
    if (refreshRunID.length && admissionID.length && service &&
        [(id)service respondsToSelector:@selector(refreshForHost:admissionID:progress:completion:)]) {
        id<RefreshServer> server = handler.server;
        NSString *runID = [refreshRunID copy];
        NSString *dispatchAdmissionID = [admissionID copy];
        [service refreshForHost:runID admissionID:dispatchAdmissionID progress:^(double value) {
            [server updateHostProgress:value runID:runID admissionID:dispatchAdmissionID];
        } completion:^(NSString *error, NSData *verification) {
            [server finishHostRefresh:error runID:runID admissionID:dispatchAdmissionID verification:verification];
        }];
    } else {
        [self reportHostRefreshUnavailable:refreshRunID ?: @"" admissionID:admissionID ?: @"" server:handler.server];
    }
}

@end

