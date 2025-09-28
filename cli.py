"""
Command-line interface for the DevTools Interactive Monitor.
"""
import argparse
import asyncio
from .monitor import EventDrivenMonitor

def main():
    parser = argparse.ArgumentParser(
        description='Attach an interactive monitor to a running browser instance.',
    )
    
    parser.add_argument(
        '--port', '-p', 
        type=int, 
        required=True,
        help='The CDP port of the target browser instance.'
    )
    
    args = parser.parse_args()

    async def run():
        monitor = EventDrivenMonitor(cdp_port=args.port)
        await monitor.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[CLI] User interrupted the process. Exiting.")
    except Exception as e:
        print(f"\n[CLI] A critical error occurred: {e}")

if __name__ == "__main__":
    main()
