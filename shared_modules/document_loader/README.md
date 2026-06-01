# Document Loader

Convert supported files into normalized text, metadata, and extracted structured elements.

## Files

- contract.md: the module contract interns should implement against.
- schemas/: machine-readable envelopes for requests, responses, config, and errors.
- examples/: synthetic examples for agent context and first tests.
- tests/contract_tests.md: required behavioral test cases.

## Rule

Product code may depend on this contract. Product code should not depend directly on the hidden provider, storage, network, parser, or model implementation behind it.
