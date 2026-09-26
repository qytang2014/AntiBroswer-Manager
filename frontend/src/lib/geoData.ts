/**
 * Standardized IANA Timezone & BCP 47 Locale definitions with intelligent region linkage.
 */

export interface TimezoneOption {
  value: string;
  label: string;
  offset: string;
}

export interface TimezoneGroup {
  region: string;
  options: TimezoneOption[];
}

export interface LocaleOption {
  value: string;
  label: string;
  nativeName?: string;
}

export const TIMEZONE_GROUPS: TimezoneGroup[] = [
  {
    region: "亚洲 (Asia)",
    options: [
      { value: "Asia/Shanghai", label: "北京 / 上海 (China)", offset: "UTC+8" },
      { value: "Asia/Hong_Kong", label: "中国香港 (Hong Kong)", offset: "UTC+8" },
      { value: "Asia/Taipei", label: "中国台北 (Taipei)", offset: "UTC+8" },
      { value: "Asia/Tokyo", label: "东京 (Tokyo)", offset: "UTC+9" },
      { value: "Asia/Seoul", label: "首尔 (Seoul)", offset: "UTC+9" },
      { value: "Asia/Singapore", label: "新加坡 (Singapore)", offset: "UTC+8" },
      { value: "Asia/Bangkok", label: "曼谷 (Bangkok)", offset: "UTC+7" },
      { value: "Asia/Ho_Chi_Minh", label: "胡志明市 / 河内 (Vietnam)", offset: "UTC+7" },
      { value: "Asia/Jakarta", label: "雅加达 (Jakarta)", offset: "UTC+7" },
      { value: "Asia/Kuala_Lumpur", label: "吉隆坡 (Kuala Lumpur)", offset: "UTC+8" },
      { value: "Asia/Manila", label: "马尼拉 (Manila)", offset: "UTC+8" },
      { value: "Asia/Kolkata", label: "新德里 / 孟买 (India)", offset: "UTC+5:30" },
      { value: "Asia/Dubai", label: "迪拜 (Dubai)", offset: "UTC+4" },
      { value: "Asia/Riyadh", label: "利雅得 (Riyadh)", offset: "UTC+3" },
      { value: "Asia/Istanbul", label: "伊斯坦布尔 (Istanbul)", offset: "UTC+3" },
      { value: "Asia/Almaty", label: "阿拉木图 (Almaty)", offset: "UTC+5" },
    ],
  },
  {
    region: "北美洲 (North America)",
    options: [
      { value: "America/New_York", label: "纽约 / 东部时间 (EST/EDT)", offset: "UTC-5 / UTC-4" },
      { value: "America/Chicago", label: "芝加哥 / 中部时间 (CST/CDT)", offset: "UTC-6 / UTC-5" },
      { value: "America/Denver", label: "丹佛 / 山地时间 (MST/MDT)", offset: "UTC-7 / UTC-6" },
      { value: "America/Los_Angeles", label: "洛杉矶 / 太平洋时间 (PST/PDT)", offset: "UTC-8 / UTC-7" },
      { value: "America/Phoenix", label: "凤凰城 (Arizona 无夏令时)", offset: "UTC-7" },
      { value: "America/Anchorage", label: "安克雷奇 (Alaska)", offset: "UTC-9" },
      { value: "Pacific/Honolulu", label: "夏威夷 / 火奴鲁鲁 (HST)", offset: "UTC-10" },
      { value: "America/Toronto", label: "多伦多 (Canada East)", offset: "UTC-5" },
      { value: "America/Vancouver", label: "温哥华 (Canada West)", offset: "UTC-8" },
      { value: "America/Mexico_City", label: "墨西哥城 (Mexico City)", offset: "UTC-6" },
    ],
  },
  {
    region: "欧洲 (Europe)",
    options: [
      { value: "Europe/London", label: "伦敦 (London / GMT)", offset: "UTC+0 / UTC+1" },
      { value: "Europe/Paris", label: "巴黎 (Paris)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Berlin", label: "柏林 / 法兰克福 (Frankfurt)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Amsterdam", label: "阿姆斯特丹 (Amsterdam)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Rome", label: "罗马 (Rome)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Madrid", label: "马德里 (Madrid)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Warsaw", label: "华沙 (Warsaw)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Vienna", label: "维也纳 (Vienna)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Stockholm", label: "斯德哥尔摩 (Stockholm)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Zurich", label: "苏黎世 (Zurich)", offset: "UTC+1 / UTC+2" },
      { value: "Europe/Moscow", label: "莫斯科 (Moscow)", offset: "UTC+3" },
      { value: "Europe/Kyiv", label: "基辅 (Kyiv)", offset: "UTC+2" },
    ],
  },
  {
    region: "大洋洲 (Oceania)",
    options: [
      { value: "Australia/Sydney", label: "悉尼 (Sydney)", offset: "UTC+10 / UTC+11" },
      { value: "Australia/Melbourne", label: "墨尔本 (Melbourne)", offset: "UTC+10 / UTC+11" },
      { value: "Australia/Brisbane", label: "布里斯班 (Brisbane)", offset: "UTC+10" },
      { value: "Australia/Perth", label: "珀斯 (Perth)", offset: "UTC+8" },
      { value: "Pacific/Auckland", label: "奥克兰 (Auckland)", offset: "UTC+12 / UTC+13" },
    ],
  },
  {
    region: "南美洲 (South America)",
    options: [
      { value: "America/Sao_Paulo", label: "圣保罗 (Sao Paulo)", offset: "UTC-3" },
      { value: "America/Buenos_Aires", label: "布宜诺斯艾利斯 (Buenos Aires)", offset: "UTC-3" },
      { value: "America/Santiago", label: "圣地亚哥 (Santiago)", offset: "UTC-4" },
      { value: "America/Bogota", label: "波哥大 (Bogota)", offset: "UTC-5" },
      { value: "America/Lima", label: "利马 (Lima)", offset: "UTC-5" },
    ],
  },
  {
    region: "非洲 (Africa)",
    options: [
      { value: "Africa/Cairo", label: "开罗 (Cairo)", offset: "UTC+2" },
      { value: "Africa/Johannesburg", label: "约翰内斯堡 (Johannesburg)", offset: "UTC+2" },
      { value: "Africa/Lagos", label: "拉各斯 (Lagos)", offset: "UTC+1" },
      { value: "Africa/Nairobi", label: "内罗毕 (Nairobi)", offset: "UTC+3" },
    ],
  },
  {
    region: "标准时区 (Standard)",
    options: [
      { value: "UTC", label: "世界协调时 (Coordinated Universal Time)", offset: "UTC+0" },
    ],
  },
];

export const LOCALE_OPTIONS: LocaleOption[] = [
  { value: "en-US", label: "English (US)", nativeName: "英语 (美国)" },
  { value: "zh-CN", label: "简体中文 (中国大陆)", nativeName: "中文 (中国)" },
  { value: "zh-TW", label: "繁體中文 (台灣)", nativeName: "中文 (台灣)" },
  { value: "zh-HK", label: "繁體中文 (香港)", nativeName: "中文 (香港)" },
  { value: "ja-JP", label: "日本語 (Japan)", nativeName: "日语" },
  { value: "ko-KR", label: "한국어 (Korea)", nativeName: "韩语" },
  { value: "en-GB", label: "English (UK)", nativeName: "英语 (英国)" },
  { value: "en-CA", label: "English (Canada)", nativeName: "英语 (加拿大)" },
  { value: "en-AU", label: "English (Australia)", nativeName: "英语 (澳大利亚)" },
  { value: "en-SG", label: "English (Singapore)", nativeName: "英语 (新加坡)" },
  { value: "de-DE", label: "Deutsch (Germany)", nativeName: "德语 (德国)" },
  { value: "fr-FR", label: "Français (France)", nativeName: "法语 (法国)" },
  { value: "es-ES", label: "Español (Spain)", nativeName: "西班牙语 (西班牙)" },
  { value: "es-MX", label: "Español (Mexico)", nativeName: "西班牙语 (墨西哥)" },
  { value: "pt-BR", label: "Português (Brazil)", nativeName: "葡萄牙语 (巴西)" },
  { value: "pt-PT", label: "Português (Portugal)", nativeName: "葡萄牙语 (葡萄牙)" },
  { value: "ru-RU", label: "Русский (Russia)", nativeName: "俄语 (俄罗斯)" },
  { value: "it-IT", label: "Italiano (Italy)", nativeName: "意大利语" },
  { value: "nl-NL", label: "Nederlands (Netherlands)", nativeName: "荷兰语" },
  { value: "tr-TR", label: "Türkçe (Turkey)", nativeName: "土耳其语" },
  { value: "vi-VN", label: "Tiếng Việt (Vietnam)", nativeName: "越南语" },
  { value: "th-TH", label: "ไทย (Thailand)", nativeName: "泰语" },
  { value: "id-ID", label: "Bahasa Indonesia", nativeName: "印尼语" },
  { value: "ms-MY", label: "Bahasa Melayu (Malaysia)", nativeName: "马来语" },
  { value: "ar-SA", label: "العربية (Saudi Arabia)", nativeName: "阿拉伯语 (沙特)" },
  { value: "ar-AE", label: "العربية (UAE)", nativeName: "阿拉伯语 (阿联酋)" },
  { value: "hi-IN", label: "हिन्दी (India)", nativeName: "印地语 (印度)" },
  { value: "pl-PL", label: "Polski (Poland)", nativeName: "波兰语" },
  { value: "uk-UA", label: "Українська (Ukraine)", nativeName: "乌克兰语" },
  { value: "sv-SE", label: "Svenska (Sweden)", nativeName: "瑞典语" },
];

/**
 * Maps standard IANA timezones to their recommended default primary locale.
 */
export const TIMEZONE_DEFAULT_LOCALE_MAP: Record<string, string> = {
  "Asia/Shanghai": "zh-CN",
  "Asia/Chongqing": "zh-CN",
  "Asia/Urumqi": "zh-CN",
  "Asia/Hong_Kong": "zh-HK",
  "Asia/Taipei": "zh-TW",
  "Asia/Tokyo": "ja-JP",
  "Asia/Seoul": "ko-KR",
  "Asia/Singapore": "en-SG",
  "Asia/Bangkok": "th-TH",
  "Asia/Ho_Chi_Minh": "vi-VN",
  "Asia/Jakarta": "id-ID",
  "Asia/Kuala_Lumpur": "ms-MY",
  "Asia/Manila": "en-US",
  "Asia/Kolkata": "hi-IN",
  "Asia/Dubai": "ar-AE",
  "Asia/Riyadh": "ar-SA",
  "Asia/Istanbul": "tr-TR",
  "Asia/Almaty": "ru-RU",

  "America/New_York": "en-US",
  "America/Chicago": "en-US",
  "America/Denver": "en-US",
  "America/Los_Angeles": "en-US",
  "America/Phoenix": "en-US",
  "America/Anchorage": "en-US",
  "Pacific/Honolulu": "en-US",
  "America/Toronto": "en-CA",
  "America/Vancouver": "en-CA",
  "America/Mexico_City": "es-MX",

  "Europe/London": "en-GB",
  "Europe/Paris": "fr-FR",
  "Europe/Berlin": "de-DE",
  "Europe/Amsterdam": "nl-NL",
  "Europe/Rome": "it-IT",
  "Europe/Madrid": "es-ES",
  "Europe/Warsaw": "pl-PL",
  "Europe/Vienna": "de-DE",
  "Europe/Stockholm": "sv-SE",
  "Europe/Zurich": "de-DE",
  "Europe/Moscow": "ru-RU",
  "Europe/Kyiv": "uk-UA",

  "Australia/Sydney": "en-AU",
  "Australia/Melbourne": "en-AU",
  "Australia/Brisbane": "en-AU",
  "Australia/Perth": "en-AU",
  "Pacific/Auckland": "en-US",

  "America/Sao_Paulo": "pt-BR",
  "America/Buenos_Aires": "es-ES",
  "America/Santiago": "es-ES",
  "America/Bogota": "es-ES",
  "America/Lima": "es-ES",

  "Africa/Cairo": "ar-SA",
  "Africa/Johannesburg": "en-US",
  "Africa/Lagos": "en-US",
  "Africa/Nairobi": "en-US",

  "UTC": "en-US",
};

/**
 * Return default recommended locale for a given IANA timezone.
 */
export function getDefaultLocaleForTimezone(timezone: string): string | null {
  return TIMEZONE_DEFAULT_LOCALE_MAP[timezone] ?? null;
}
