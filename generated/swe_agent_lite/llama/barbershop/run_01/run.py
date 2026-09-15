import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Define constants
SIMULATION_TIME = 1000000.0  # Default simulation time in seconds
QUEUE_CAPACITY = 8  # Maximum number of customers in the reception desk queue
RECEPTION_PROCESSING_TIME = 5  # Time in seconds for reception processing
INSPECTION_PROCESSING_TIME = 7  # Time in seconds for hair inspection
CUTTING_PROCESSING_TIME = 20  # Time in seconds for hair cutting

# Define the simulation environment
class BarberShopSimulation:
    def __init__(self, env, reception_queue, inspection_phase, cutting_phase):
        self.env = env
        self.reception_queue = reception_queue
        self.inspection_phase = inspection_phase
        self.cutting_phase = cutting_phase

    def run(self):
        # Initialize the simulation
        self.env.process(self.reception_desk())
        self.env.process(self.inspection())
        self.env.process(self.cutting())

        # Run the simulation
        self.env.run(until=SIMULATION_TIME)

    def reception_desk(self):
        while True:
            # Wait for a new customer
            customer = yield self.env.event
            if len(self.reception_queue) < QUEUE_CAPACITY:
                # Add customer to the queue
                self.reception_queue.append(customer)
                print(f"{self.env.now}: Customer added to reception queue")
            else:
                print(f"{self.env.now}: Reception queue is full, customer ignored")

            # Process the next customer in the queue
            if self.reception_queue:
                yield self.env.timeout(RECEPTION_PROCESSING_TIME)
                customer = self.reception_queue.pop(0)
                # Send customer to inspection phase
                self.inspection_phase.process(customer)

    def inspection(self):
        while True:
            # Wait for a customer from the reception desk
            customer = yield self.inspection_phase.event
            # Process the customer
            yield self.env.timeout(INSPECTION_PROCESSING_TIME)
            # Send customer to cutting phase
            self.cutting_phase.process(customer)

    def cutting(self):
        while True:
            # Wait for a customer from the inspection phase
            customer = yield self.cutting_phase.event
            # Process the customer
            yield self.env.timeout(CUTTING_PROCESSING_TIME)
            # Signal back to inspection phase that cutting is done
            self.inspection_phase.done()

# Define the phases
class ReceptionDesk:
    def __init__(self):
        self.queue = []
        self.event = simpy.Event(self.env)

    def process(self, customer):
        self.queue.append(customer)
        self.event.succeed()

class InspectionPhase:
    def __init__(self):
        self.event = simpy.Event(self.env)
        self.done_event = simpy.Event(self.env)

    def process(self, customer):
        self.event.succeed(customer)

    def done(self):
        self.done_event.succeed()

class CuttingPhase:
    def __init__(self):
        self.event = simpy.Event(self.env)

    def process(self, customer):
        self.event.succeed(customer)

# Main function
def main():
    # Create the simulation environment
    env = simpy.Environment()
    reception_queue = []
    inspection_phase = InspectionPhase()
    cutting_phase = CuttingPhase()
    simulation = BarberShopSimulation(env, reception_queue, inspection_phase, cutting_phase)

    # Start the simulation
    simulation.run()

if __name__ == '__main__':
    main()