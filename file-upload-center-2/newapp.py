try:
    if from_date:
        datetime.strptime(from_date, '%Y-%m-%d')
    if to_date:
        datetime.strptime(to_date, '%Y-%m-%d')
    if from_date and to_date and from_date > to_date:
        logging.warning('From date %s is after to date %s', from_date, to_date)
        return jsonify({
            'status': 'error',
            'message': 'From date cannot be after to date'
        }), 400
except ValueError:
    logging.error('Invalid date format: from_date=%s, to_date=%s', from_date, to_date)
    return jsonify({
        'status': 'error',
        'message': 'Invalid date format'
    }), 400