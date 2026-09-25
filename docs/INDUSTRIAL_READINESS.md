# Industrial hardening status

This is an engineering progress record, not an industrial certification or a claim that every robot is supported.

## Implemented software hardening

- Studio defaults to local clients, explicit host names and browser origins. HTTP and WebSocket requests from unapproved origins are rejected. Remote clients require token authentication and TLS.
- Optional `PYROBOT_STUDIO_TOKEN` protects local access too. Use 32–128 random URL-safe characters. Studio prompts for it and retains it only in memory. WebSocket credentials use a subprotocol header, not a URL query. Do not enable request-header logging that records credentials.
- Configure `PYROBOT_STUDIO_ORIGINS` as a comma-separated list of exact frontend origins and `PYROBOT_STUDIO_HOSTS` as accepted backend hostnames when using a custom setup. The default local frontend origin is port 5173. Explicitly configure other Vite ports.
- CAN writes use a dedicated worker, bounded 64-frame queue, configurable send timeout and queue-age limit. Full/expired queues fail the node. Stop discards pending commands. In-flight sends can still complete. Driver timeouts depend on the driver's implementation.
- Graph supervision detects a failed bus or no bus progress for two seconds. This is a coarse fault detector, not a real-time safety deadline.
- Duplicate plugin IDs fail registry loading rather than silently replacing a driver.
- Deployment selection survives restart, with checksum and compatibility validation. The recovered graph is always stopped. Logs rotate on disk. A two-second operation-lock timeout reports contention; validation/deployment work no longer runs on the HTTP event loop.
- `requirements.lock.txt` captures the tested Python environment. Install with `python -m pip install -r requirements.lock.txt`. It is a version snapshot, not a hash-verified supply-chain lock. The GitHub workflow checks Python 3.14 on Windows/Linux and builds/lints the frontend. Remote CI and Linux compatibility are not proven until those jobs pass.

## Hardware-independent architecture

Serial and Ethernet should be the primary transport adapters, with CAN and RS485 adapters where required. Transport, device protocol and robot geometry are separate concerns. Merely opening a serial port does not make a device compatible.

Each actuator adapter must define command units and limits, acknowledgement semantics, stale-command handling, arming/disarming, device-side watchdog configuration, stop acknowledgement and recovery behaviour. Generic byte writers are not qualified actuator drivers. A host-side timeout does not prove the motor stopped.

Examples to support through separate protocol adapters:

- RPLIDAR: use the [SLAMTEC SDK/protocol](https://github.com/Slamtec/rplidar_sdk), selected for the actual sensor model and serial/Ethernet interface.
- Pololu controllers: use the selected controller's protocol and configure its device-side timeout. The [Simple Motor Controller G2 guide](https://www.pololu.com/docs/0J77/all) is one example; it is not a protocol for every Pololu product.
- N20 and other encoder motors: connect through an appropriate motor driver and encoder controller. Their mechanical motor type does not define a serial/Ethernet protocol.
- Zeltec/CAN/RS485 hardware: obtain the exact controller model and command/register specification before writing the adapter.
- Pixhawk-class systems: use [MAVLink microservices](https://mavlink.io/en/services/) and flight-stack-specific arming/failsafe configuration. Heartbeat reception alone is not a verified stop mechanism.

These adapters are a roadmap, not newly implemented hardware support.

## Still blocking industrial use

1. Process-level isolation and termination of hung plugins/drivers, including owned subprocess cleanup. In-process threads still cannot be forcibly contained.
2. Real actuator adapters with independent device watchdogs, stop acknowledgement, firmware support and measured physical stopping behaviour.
3. Comprehensive message QoS, expiry, delivery acknowledgement, deadline/liveliness policy and overload metrics; high-volume binary sensor transport.
4. Bounded startup/shutdown throughout all plugins. Agent contention timeouts do not interrupt the underlying operation.
5. Least-privilege services, role-based authorization, token rotation, signed/verified plugin deployment and durable operator audit trails. Local no-token mode assumes trusted local processes.
6. Self-contained deployment bundles, operator-controlled rollback, service installers and validated upgrades.
7. General live transforms, mature localization/navigation, manipulation planning and calibrated hardware interfaces.
8. Hardware-in-loop fault injection, endurance/load benchmarks and validated Windows/Linux/ARM support.
9. Project licensing and third-party redistribution review. No license was chosen on the owner's behalf.

Keep external safety controllers, hardware watchdogs and physical emergency stops independent of Studio. Qualify one complete hardware workflow at a time without putting robot-specific logic into the core runtime.
