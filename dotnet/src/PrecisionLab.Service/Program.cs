using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using PrecisionLab.Acquisition;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Drivers.Builtin;
using PrecisionLab.Service;

HostApplicationBuilder builder = Host.CreateApplicationBuilder(args);

string localData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
string sessionDirectory = Path.Combine(localData, "PrecisionLab", "Sessions");

builder.Services.AddSingleton<MeasurementHub>();
builder.Services.AddSingleton<IMeasurementSink>(
    _ => new JsonLinesMeasurementSink(sessionDirectory));
builder.Services.AddSingleton<MeasurementPipeline>();
builder.Services.AddSingleton<IMeasurementPublisher>(
    provider => provider.GetRequiredService<MeasurementPipeline>());
builder.Services.AddHostedService(
    provider => provider.GetRequiredService<MeasurementPipeline>());

builder.Services.AddSingleton<IInstrumentDriverFactory, BuiltinInstrumentDriverFactory>();
builder.Services.AddSingleton<AcquisitionCoordinator>();
builder.Services.AddHostedService(
    provider => provider.GetRequiredService<AcquisitionCoordinator>());

builder.Services.AddHostedService<ControlPipeServer>();
builder.Services.AddHostedService<DataPipeServer>();

await builder.Build().RunAsync().ConfigureAwait(false);
