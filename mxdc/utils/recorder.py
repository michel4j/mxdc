import pandas


class DataSaver(object):
    """
    Record data in rows and save them to a csv file

    :param filename: name of csv file to save data to
    :param headers: header field names
    """
    def __init__(self, filename, *headers):
        self.filename = filename
        self.headers = headers
        self.data = []

    def add_row(self, *values):
        """
        Add a new row of data to the recorder and update the output file contents
        :param values: values corresponding to the header fields specified when creating the recorder
        """
        assert len(values) == len(self.headers)
        self.data.append(values)
        df = pandas.DataFrame(self.data, columns=self.headers)
        df.to_csv(self.filename)
