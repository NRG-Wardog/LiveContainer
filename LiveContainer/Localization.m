//
//  Localization.m
//  LiveContainer
//
//  Created by s s on 2024/9/21.
//
#import "Localization.h"
#import "utils.h"

@implementation NSString (Localization)

// Class method for the English language bundle
+ (NSBundle *)enBundle {
    static NSBundle *enBundle = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        NSString *language = @"en";
        NSString *path = [[NSUserDefaults lcMainBundle] pathForResource:language ofType:@"lproj"];
        enBundle = [NSBundle bundleWithPath:path];
    });
    return enBundle;
}

// P2_NATIVE_HOST_LANGUAGE_V1: use the defaults and bundle captured before any
// guest swaps NSUserDefaults.standardUserDefaults or NSBundle.mainBundle. Never
// inspect or mutate the guest's language settings, including AppleLanguages.
static NSString *LCHostLanguageCode(void) {
    id saved = [NSUserDefaults.lcUserDefaults objectForKey:@"V3AppLanguage"];
    NSString *raw = [saved isKindOfClass:NSString.class] ? saved : @"en";
    NSArray<NSString *> *parts = [[[raw stringByReplacingOccurrencesOfString:@"_" withString:@"-"] lowercaseString] componentsSeparatedByString:@"-"];
    NSString *language = parts.firstObject;
    if ([language isEqualToString:@"he"]) return @"he";
    if ([language isEqualToString:@"ru"]) return @"ru";
    if ([language isEqualToString:@"zh"]) {
        NSString *scriptOrRegion = parts.count > 1 ? parts[1] : @"";
        if ([@[@"hant", @"tw", @"hk", @"mo"] containsObject:scriptOrRegion]) return @"zh-Hant";
        return @"zh-Hans";
    }
    return @"en";
}

- (NSString *)localized {
    NSBundle *hostBundle = NSUserDefaults.lcMainBundle;
    for (NSString *code in @[LCHostLanguageCode(), @"en"]) {
        NSString *path = [hostBundle pathForResource:code ofType:@"lproj"];
        if (!path) continue;
        NSBundle *bundle = [NSBundle bundleWithPath:path];
        NSString *missing = @"__V3_MISSING_LOCALIZATION__";
        NSString *value = [bundle localizedStringForKey:self value:missing table:nil];
        if (value && ![value isEqualToString:missing]) return value;
    }
    return self;
}

// Instance method for localization with format
- (NSString *)localizeWithFormat:(NSString*)arg1, ... {
    va_list args;
    va_start(args, arg1);
    NSString *formattedString = [NSString localizedStringWithFormat:[self localized], arg1, args];
//    NSString *formattedString = [[NSString alloc] localized:[self localized] arguments:arg1, args];
    va_end(args);
    return formattedString;
}

@end
