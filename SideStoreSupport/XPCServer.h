//
//  XPCServer.h
//  LiveContainer
//
//  Created by s s on 2025/7/20.
//

#import <Foundation/Foundation.h>
#import <UserNotifications/UserNotifications.h>

__attribute__((swift_attr("@Sendable")))
@protocol RefreshServer
- (void)updateProgress:(double)value;
- (void)finish:(NSString*)error;
// LC_REFRESH_RESULT_XPC_V1
- (void)finishRefresh:(NSString* _Nullable)error runID:(NSString* _Nonnull)runID verification:(NSData* _Nullable)verification NS_SWIFT_NAME(finishRefresh(_:runID:verification:));
- (void)onConnection:(NSXPCConnection*)connection;
- (void)finishedLaunching;
- (void)addNotificationRequest:(UNNotificationRequest*)request;
- (void)removePendingNotificationRequestsWithIdentifiers:(NSArray<NSString*>*)identifiers;
@end

@protocol RefreshClient
// V3_COMMAND_PATCH_V1: primitive NSData only; the service validates its schema.
- (void)v3Execute:(NSData* _Nonnull)request reply:(void (^ _Nonnull)(NSData* _Nonnull))reply NS_SWIFT_NAME(v3Execute(_:reply:));
- (void)refreshAllAppsWithIdentifier:(NSString*)identifier mangledTypeName:(NSString *)mangledTypeName refreshRunID:(NSString* _Nullable)refreshRunID;
@end

@interface LiveProcessSideStoreHandler : NSObject
@property (class, readonly, strong) LiveProcessSideStoreHandler* shared;
@property NSXPCConnection* connection;
@property NSObject<RefreshServer>* server;

@end

NSXPCListener* startAnonymousListener(NSObject<RefreshServer>* reporter);
NSData* bookmarkForURL(NSURL* url);

void installSideStoreHooks(void);
void installSideStoreNotificationHooks(void);

@interface SideStoreClient : NSObject<RefreshClient>
@property (class, readonly) SideStoreClient* shared;
- (void) relaunchLC;
@end

// LC_SERVICE_CONNECTION_V1: preserve NSError and nullable launch results.
@class NSExtension;
BOOL LCPrepareServiceStorage(NSURL * _Nonnull url, NSError * _Nullable * _Nullable error) __attribute__((swift_error(none)));
NSData * _Nullable LCCreateServiceBookmark(NSURL * _Nonnull url, NSError * _Nullable * _Nullable error) __attribute__((swift_error(none)));
void LCLaunchServiceExtension(NSExtension * _Nonnull extension, NSExtensionItem * _Nonnull item,
    void (^ _Nonnull completion)(NSUUID * _Nullable identifier, NSError * _Nullable error));
