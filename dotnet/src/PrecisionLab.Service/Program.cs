using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using PrecisionLab.Acquisition;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Drivers.Builtin;
using PrecisionLab.Drivers.Visa;
using PrecisionLab.Service;
using PrecisionLab.Storage;

HostApplicationBuilder builder = Host.CreateApplicationBuilder(args);
string dataDirectory = ResolveDataDirectory(args);
string databasePath = Path.Combine(dataDirectory, "precisionlab-sessions.db");

builder.Services.AddSingleton<ISessionStore>(new SqliteSessionStore(databasePath));
builder.Services.AddSingleton<IVisaBackend, IviVisaBackend>();
builder.Services.AddSingleton<VisaInstrumentDriverFactory>();
builder.Services.AddSingleton<IInstrumentDriverFactory>(
    provider => new BuiltinInstrumentDriverFactory(
        provider.GetRequiredService<VisaInstrumentDriverFactory>()));
builder.Services.AddSingleton<MeasurementHub>();
builder.Services.AddSingleton<MeasurementPipeline>();
builder.Services.AddSingleton<IMeasurementPublisher>(
    provider => provider.GetRequiredService<MeasurementPipeline>());
builder.Services.AddSingleton<IHostedService>(
    provider => provider.GetRequiredService<MeasurementPipeline>());
builder.Services.AddSingleton<AcquisitionCoordinator>();
builder.Services.AddSingleton<IHostedService>(
    provider => provider.GetRequiredService<AcquisitionCoordinator>());
builder.Services.AddHostedService<ControlPipeServer>();
builder.Services.AddHostedService<DataPipeServer>();

await builder.Build().RunAsync().ConfigureAwait(false);

static string ResolveDataDirectory(string[] arguments)
{
    int index = Array.FindIndex(
        arguments,
        item => item.Equals("--data-dir", StringComparison.OrdinalIgnoreCase));
    if (index >= 0 && index + 1 < arguments.Length)
    {
        return Path.GetFullPath(arguments[index + 1]);
    }

    return Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PrecisionLab");
}
