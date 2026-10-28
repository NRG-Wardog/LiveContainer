#import <Foundation/Foundation.h>
@@STORAGE@@
@interface LCUtils:NSObject
+ (NSUInteger)beginGuestLaunchDiagnostics;
+ (void)recordGuestLaunchDiagnostic:(NSUInteger)generation phase:(NSString *)phase;
+ (NSString *)guestLaunchDiagnosticSnapshot;
+ (void)complete:(NSUInteger)generation pid:(NSNumber *)pid error:(NSError *)error callback:(void (^)(NSNumber *,NSError *))completionHandler;
@end
@implementation LCUtils
@@METHODS@@
+ (void)complete:(NSUInteger)generation pid:(NSNumber *)pid error:(NSError *)error callback:(void (^)(NSNumber *,NSError *))completionHandler {
    void (^finish)(NSNumber *, NSError *) = ^(NSNumber *pid, NSError *error) {@@FINISH@@};
    finish(pid,error);
}
@end
static void check(BOOL x,NSString *why){if(!x){fprintf(stderr,"FAIL %s\n",why.UTF8String);exit(1);}}
int main(void){@autoreleasepool{
 check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"state=not_started"],@"initial state");
 NSUInteger first=[LCUtils beginGuestLaunchDiagnostics];[LCUtils recordGuestLaunchDiagnostic:first phase:@"signing"];
 check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"phases=admitted,signing"],@"signing reset");
 NSString *before=[LCUtils guestLaunchDiagnosticSnapshot];[LCUtils recordGuestLaunchDiagnostic:first phase:nil];[LCUtils recordGuestLaunchDiagnostic:first phase:(id)NSNull.null];check([[LCUtils guestLaunchDiagnosticSnapshot] isEqualToString:before],@"non-string rejected");[LCUtils recordGuestLaunchDiagnostic:first phase:@"user@example.com /private/path pairing-secret"];
 check([[LCUtils guestLaunchDiagnosticSnapshot] isEqualToString:before],@"allowlist");
 NSMutableString *mutable=[@"signed" mutableCopy];[LCUtils recordGuestLaunchDiagnostic:first phase:mutable];[mutable appendString:@" user@example.com"];
 check(![[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"user@example.com"],@"immutable canonical token");
 for(int i=0;i<100;i++) [LCUtils recordGuestLaunchDiagnostic:first phase:@"virtual_window_requested"];
 check(LCGuestDiagnosticPhases.count==16&&[LCUtils guestLaunchDiagnosticSnapshot].length<1200,@"bounded");
 NSUInteger second=[LCUtils beginGuestLaunchDiagnostics];[LCUtils recordGuestLaunchDiagnostic:second phase:@"signing"];
 before=[LCUtils guestLaunchDiagnosticSnapshot];[LCUtils recordGuestLaunchDiagnostic:first phase:@"completed"];
 check([[LCUtils guestLaunchDiagnosticSnapshot] isEqualToString:before],@"stale generation");
 [LCUtils recordGuestLaunchDiagnostic:second phase:@"completed"];before=[LCUtils guestLaunchDiagnosticSnapshot];
 [LCUtils recordGuestLaunchDiagnostic:second phase:@"signing"];check([[LCUtils guestLaunchDiagnosticSnapshot] isEqualToString:before],@"terminal immutable");
 NSUInteger third=[LCUtils beginGuestLaunchDiagnostics];check(![[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"completed"],@"new attempt removes old success");
 [LCUtils recordGuestLaunchDiagnostic:third phase:@"signing_failed"];check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"state=failed"],@"sign failure");
 NSArray *codes=@[@411,@412,@410,@999];NSArray *phases=@[@"lookup_failed",@"host_attachment_failed",@"early_exit",@"launch_failed"];
 for(NSUInteger i=0;i<codes.count;i++){
  NSUInteger token=[LCUtils beginGuestLaunchDiagnostics];NSError *error=[NSError errorWithDomain:@"LiveContainerReturn" code:[codes[i] integerValue] userInfo:@{NSLocalizedDescriptionKey:@"user@example.com /private/path"}];
  __block int callbacks=0;[LCUtils complete:token pid:nil error:error callback:^(NSNumber *pid,NSError *forwarded){callbacks++;check(forwarded==error&&pid==nil,@"completion identity");}];
  NSString *snapshot=[LCUtils guestLaunchDiagnosticSnapshot];check(callbacks==1&&[snapshot containsString:phases[i]],@"classification");check(![snapshot containsString:@"user@example"]&&![snapshot containsString:@"private/path"]&&![snapshot containsString:@"LiveContainerReturn"],@"redaction");
 }
 NSUInteger old=[LCUtils beginGuestLaunchDiagnostics],current=[LCUtils beginGuestLaunchDiagnostics];before=[LCUtils guestLaunchDiagnosticSnapshot];
 [LCUtils complete:old pid:@123 error:nil callback:nil];check([[LCUtils guestLaunchDiagnosticSnapshot] isEqualToString:before],@"late completion");
 [LCUtils complete:current pid:@123 error:nil callback:nil];check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"pid_present,completed"],@"pid boolean only");check(![[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"123"],@"pid redacted");
 for(NSNumber *pid in @[@0,@(-1)]){NSUInteger token=[LCUtils beginGuestLaunchDiagnostics];[LCUtils complete:token pid:pid error:nil callback:nil];check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"callback_no_pid"]&&[[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"state=failed"],@"nonpositive pid not success");}
 NSUInteger token=[LCUtils beginGuestLaunchDiagnostics];[LCUtils complete:token pid:nil error:nil callback:nil];check([[LCUtils guestLaunchDiagnosticSnapshot] containsString:@"callback_no_pid"],@"nil pid not success");
 puts("GUEST_LAUNCH_DIAGNOSTICS_PASS");return 0;
}}
