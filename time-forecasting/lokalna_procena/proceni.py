"""Ispisuje samo procenjeno trajanje; ne izvršava ulazni fajl."""
import argparse
import json
from pathlib import Path
from runtime_estimator import RuntimeEstimator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fajl', type=Path)
    parser.add_argument('--baza', type=Path, help='Alternativna kalibraciona JSON baza (npr. ML).')
    parser.add_argument('--detalji', action='store_true', help='JSON sa dijagnostikom izabranog modela.')
    options = parser.parse_args()
    try:
        estimator = RuntimeEstimator(options.baza or Path(__file__).resolve().parent / 'podaci/kalibracija.json')
        source = options.fajl.read_text(encoding='utf-8')
        if options.detalji and estimator.model and estimator.model['type'] == 'phase_static' and not estimator.records:
            from faze_model import predict
            details = predict(estimator.model, source, options.fajl)
            seconds = details['seconds']
        else:
            seconds, mode = estimator.estimate(source, path=options.fajl)
            details = {'seconds': seconds, 'mode': mode}
            if options.detalji and mode == 'model' and estimator.model['type'] == 'ml_v2':
                from ml_v2 import predict
                details = predict(estimator.model, source)
    except (OSError, ValueError, SyntaxError) as error:
        parser.exit(1, f'Greška: {error}\n')
    print(json.dumps(details, ensure_ascii=False) if options.detalji else f'{seconds:.6f}')


if __name__ == '__main__':
    main()
