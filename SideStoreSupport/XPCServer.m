#import "../LiveContainer/FoundationPrivate.h"
#import "../LiveContainer/LCContainerStorage.h"
//
//  XPCServer.m
//  LiveContainer
//
//  Created by s s on 2025/7/20.
//

#import <Foundation/Foundation.h>
#import "XPCServer.h"

@interface ServerDelegate : NSObject <NSXPCListenerDelegate>
@property NSObject<RefreshServer>* reporter;
@end

@implementation ServerDelegate

- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)newConnection {
    newConnection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RefreshServer)];
    newConnection.exportedObject = self.reporter;
    [self.reporter onConnection:newConnection];
    // V3_XPC_PEER_ADMISSION_V1: RefreshHandler resumes only the launched extension peer.
    return YES;
}

@end

ServerDelegate* staticDelegate = nil;

NSXPCListener* startAnonymousListener(NSObject<RefreshServer>* reporter) {
    ServerDelegate *delegate = [ServerDelegate new];
    staticDelegate = delegate;
    delegate.reporter = reporter;
    NSXPCListener *listener = [NSXPCListener anonymousListener];
    listener.delegate = delegate;
    [listener resume];
    return listener;
}

NSData* bookmarkForURL(NSURL* url) {
    return [url bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:0 relativeToURL:0 error:0];
}

BOOL LCPrepareServiceStorage(NSURL *url, NSError **error) {
    return LCPrepareContainerDirectories(url.path, error);
}
NSData *LCCreateServiceBookmark(NSURL *url, NSError **error) {
    return [url bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:nil relativeToURL:nil error:error];
}
void LCLaunchServiceExtension(NSExtension *extension, NSExtensionItem *item, void (^completion)(NSUUID *, NSError *)) {
    [extension beginExtensionRequestWithInputItems:@[item] completion:^(NSUUID *identifier) {
        // The private API reports only an identifier. Nil means no identifier
        // was observed; it does not establish why extension startup failed.
        NSError *error = identifier ? nil : [NSError errorWithDomain:@"io.sidestore.LiveContainer.ExtensionLaunch" code:1 userInfo:nil];
        completion(identifier, error);
    }];
}
