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
- (void)reportHostRefreshUnavailable:(NSString *)runID server:(id<RefreshServer>)server;

@end

static LiveProcessSideStoreHandler* handler = nil;
void installSideStoreHooks(void);

@protocol V3CommandService
+ (void)execute:(NSData *)request reply:(void (^)(NSData *))reply;
+ (void)refreshForHost:(NSString *)runID
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
    if(!handler) {
        return;
    }
    // V3_DIRECT_HOST_REFRESH_V1: only the service with the explicit admission
    // may clear state or start the canonical backend. No private AppIntent run.
    Class<V3CommandService> service = (Class<V3CommandService>)NSClassFromString(@"V3SideStoreService");
    if (refreshRunID.length && service &&
        [(id)service respondsToSelector:@selector(refreshForHost:progress:completion:)]) {
        id<RefreshServer> server = handler.server;
        NSString *runID = [refreshRunID copy];
        [service refreshForHost:runID progress:^(double value) {
            [server updateProgress:value];
        } completion:^(NSString *error, NSData *verification) {
            [server finishRefresh:error runID:runID verification:verification];
        }];
    } else {
        [self reportHostRefreshUnavailable:refreshRunID ?: @"" server:handler.server];
    }
}

@end

