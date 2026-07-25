using System.ComponentModel;
using System.Globalization;
using System.Resources;
using CommunityToolkit.Mvvm.ComponentModel;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class LocalizationService : ObservableObject
{
    private readonly ResourceManager _resources = new(
        "PrecisionLab.Desktop.Wpf.Resources.Strings",
        typeof(LocalizationService).Assembly);
    private CultureInfo _culture = CultureInfo.GetCultureInfo("en");

    public string CurrentLanguage => _culture.Name.StartsWith(
        "zh",
        StringComparison.OrdinalIgnoreCase)
        ? "zh-CN"
        : "en";

    [IndexerName("Item")]
    public string this[string key] =>
        _resources.GetString(key, _culture) ?? key;

    public void Toggle()
    {
        _culture = CurrentLanguage == "en"
            ? CultureInfo.GetCultureInfo("zh-CN")
            : CultureInfo.GetCultureInfo("en");
        CultureInfo.CurrentUICulture = _culture;
        OnPropertyChanged("Item[]");
        OnPropertyChanged(nameof(CurrentLanguage));
    }
}
